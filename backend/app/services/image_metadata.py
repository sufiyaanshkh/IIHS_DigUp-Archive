from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from threading import RLock
from typing import Any


class MetadataToolUnavailable(RuntimeError):
    pass


class MetadataExtractionFailed(RuntimeError):
    pass


_CACHE: OrderedDict[tuple[int, int, int, int, str], dict[str, str | None]] = OrderedDict()
_CACHE_LOCK = RLock()
_CACHE_LIMIT = 128


def _value(tags: dict[str, Any], *names: str) -> Any:
    return next((tags[name] for name in names if tags.get(name) not in (None, "")), None)


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value) if math.isfinite(value) else None
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(Fraction(value)) if isinstance(value, str) and "/" in value else float(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _decimal(value: float) -> str:
    return format(value, ".12g")


def _shutter(value: Any) -> str | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    fraction = Fraction(number).limit_denominator(100_000)
    if fraction.numerator == 0:
        return f"{_decimal(number)} sec"
    return f"{fraction.numerator} sec" if fraction.denominator == 1 else f"{fraction.numerator}/{fraction.denominator} sec"


def _capture_time(tags: dict[str, Any], kind: str) -> str | None:
    if kind == "video":
        value = _text(_value(tags, "ExifIFD:DateTimeOriginal", "EXIF:DateTimeOriginal",
                             "XMP-exif:DateTimeOriginal", "ItemList:ContentCreateDate",
                             "UserData:ContentCreateDate"))
    else:
        value = _text(_value(tags, "ExifIFD:DateTimeOriginal", "EXIF:DateTimeOriginal",
                             "XMP-exif:DateTimeOriginal"))
    if not value:
        return None
    match = re.fullmatch(
        r"(\d{4}[:-]\d{2}[:-]\d{2}[ T]\d{2}:\d{2}:\d{2})(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?",
        value,
    )
    if not match or value.startswith("0000"):
        return None
    base, fraction, offset = match.groups()
    try:
        datetime.strptime(base.replace("T", " ").replace("-", ":", 2), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if kind != "video" or any(tags.get(name) for name in (
        "ExifIFD:DateTimeOriginal", "EXIF:DateTimeOriginal", "XMP-exif:DateTimeOriginal"
    )):
        subsecond = _text(_value(tags, "ExifIFD:SubSecTimeOriginal", "EXIF:SubSecTimeOriginal"))
        if not fraction and subsecond and re.fullmatch(r"\d+", subsecond):
            fraction = "." + subsecond
        if not offset:
            candidate = _text(_value(tags, "ExifIFD:OffsetTimeOriginal", "EXIF:OffsetTimeOriginal",
                                     "XMP-exif:OffsetTimeOriginal"))
            if candidate:
                if not re.fullmatch(r"Z|[+-]\d{2}:?\d{2}", candidate):
                    return None
                offset = candidate
    if offset and offset != "Z":
        hours, minutes = offset[1:].replace(":", "")[:2], offset[1:].replace(":", "")[2:]
        if int(hours) > 23 or int(minutes) > 59:
            return None
    return base + (fraction or "") + (offset or "")


def _coordinate(value: Any, reference: Any, positive: str, negative: str, limit: float) -> str | None:
    text = _text(value)
    number = _number(value)
    if text is None or number is None or abs(number) > limit:
        return None
    ref = _text(reference)
    if not ref or ref.upper() not in (positive, negative):
        return None
    text = text.lstrip("+-")
    return ("-" if ref.upper() == negative else "") + text


def _location(tags: dict[str, Any]) -> str | None:
    latitude = _coordinate(_value(tags, "GPS:GPSLatitude"), _value(tags, "GPS:GPSLatitudeRef"), "N", "S", 90)
    longitude = _coordinate(_value(tags, "GPS:GPSLongitude"), _value(tags, "GPS:GPSLongitudeRef"), "E", "W", 180)
    if latitude is not None and longitude is not None:
        return f"{latitude}, {longitude}"
    xmp_latitude = _text(tags.get("XMP-exif:GPSLatitude"))
    xmp_longitude = _text(tags.get("XMP-exif:GPSLongitude"))
    xmp_lat_number, xmp_lon_number = _number(xmp_latitude), _number(xmp_longitude)
    if (xmp_latitude and xmp_longitude and xmp_lat_number is not None and xmp_lon_number is not None
            and abs(xmp_lat_number) <= 90 and abs(xmp_lon_number) <= 180):
        return f"{xmp_latitude}, {xmp_longitude}"
    value = _text(_value(tags, "Keys:GPSCoordinates", "QuickTime:GPSCoordinates",
                         "ItemList:GPSCoordinates", "UserData:GPSCoordinates"))
    if not value:
        return None
    match = re.fullmatch(r"\s*([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)(?:[+-]\d+(?:\.\d+)?)?/?\s*", value)
    if match:
        lat, lon = match.groups()
    else:
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)(?:\s+[+-]?\d+(?:\.\d+)?)?\s*", value)
        if not match:
            return None
        lat, lon = match.groups()
    if abs(float(lat)) > 90 or abs(float(lon)) > 180:
        return None
    return f"{lat}, {lon}"


def _dimensions(tags: dict[str, Any]) -> str | None:
    for group in ("File", "PNG", "IFD0", "Track1"):
        width, height = _number(tags.get(f"{group}:ImageWidth")), _number(tags.get(f"{group}:ImageHeight"))
        if width is not None and height is not None and width > 0 and height > 0 and width.is_integer() and height.is_integer():
            return f"{int(width)} × {int(height)} px"
    size = _text(tags.get("Composite:ImageSize"))
    match = re.fullmatch(r"([1-9]\d*)[ x×]+([1-9]\d*)", size or "")
    return f"{match.group(1)} × {match.group(2)} px" if match else None


def _white_balance(value: Any, is_exif: bool) -> str | None:
    text = _text(value)
    if not text:
        return None
    if is_exif and text in ("0", "1"):
        return {"0": "Auto", "1": "Manual"}[text]
    known = {
        "auto": "Auto", "automatic": "Auto", "manual": "Manual", "daylight": "Daylight",
        "cloudy": "Cloudy", "shade": "Shade", "tungsten": "Tungsten",
        "fluorescent": "Fluorescent", "incandescent": "Incandescent",
        "flash": "Flash", "custom": "Custom",
    }
    if text.casefold() in known:
        return known[text.casefold()]
    return text if re.fullmatch(r"[1-9]\d{2,4}\s*K", text, re.IGNORECASE) else None


def _join_make_model(make: str | None, model: str | None) -> str | None:
    if make and model and (model.casefold() == make.casefold() or model.casefold().startswith(make.casefold() + " ")):
        return model
    return " ".join(part for part in (make, model) if part) or None


def _normalize(tags: dict[str, Any], kind: str) -> dict[str, str | None]:
    make = _text(_value(tags, "IFD0:Make", "EXIF:Make", "XMP-tiff:Make", "Keys:Make", "QuickTime:Make", "ItemList:Make", "UserData:Make"))
    model = _text(_value(tags, "IFD0:Model", "EXIF:Model", "XMP-tiff:Model", "Keys:Model", "QuickTime:Model", "ItemList:Model", "UserData:Model"))
    camera = _join_make_model(make, model)
    lens_make = _text(_value(tags, "ExifIFD:LensMake", "EXIF:LensMake", "XMP-exifEX:LensMake"))
    lens_model = _text(_value(tags, "ExifIFD:LensModel", "EXIF:LensModel", "XMP-exifEX:LensModel",
                              "XMP-aux:Lens", "Keys:LensModel", "VideoKeys:LensModel",
                              "QuickTime:LensModel", "Composite:LensID"))
    aperture = _number(_value(tags, "ExifIFD:FNumber", "EXIF:FNumber", "XMP-exif:FNumber", "Keys:FNumber", "QuickTime:FNumber"))
    iso = _number(_value(tags, "ExifIFD:ISO", "ExifIFD:PhotographicSensitivity", "EXIF:ISO", "XMP-exif:ISO",
                         "Keys:ISO", "QuickTime:ISO"))
    ev = _number(_value(tags, "ExifIFD:ExposureCompensation", "EXIF:ExposureCompensation", "XMP-exif:ExposureBiasValue",
                        "Keys:ExposureCompensation", "QuickTime:ExposureCompensation"))
    white = _value(tags, "ExifIFD:WhiteBalance", "EXIF:WhiteBalance", "XMP-exif:WhiteBalance", "Keys:WhiteBalance",
                   "QuickTime:WhiteBalance")
    white_balance = _white_balance(white, any(
        name in tags and tags[name] not in (None, "") for name in ("ExifIFD:WhiteBalance", "EXIF:WhiteBalance", "XMP-exif:WhiteBalance")
    ))
    return {
        "camera": camera,
        "lens": _join_make_model(lens_make, lens_model),
        "aperture": f"f/{_decimal(aperture)}" if aperture is not None and aperture > 0 else None,
        "iso": _decimal(iso) if iso is not None and iso > 0 else None,
        "shutter_speed": _shutter(_value(tags, "ExifIFD:ExposureTime", "EXIF:ExposureTime", "XMP-exif:ExposureTime",
                                         "Keys:ExposureTime", "QuickTime:ExposureTime")),
        "white_balance": white_balance,
        "exposure_compensation": f"{ev:+.12g} EV" if ev is not None else None,
        "location": _location(tags),
        "capture_time": _capture_time(tags, kind),
        "dimensions": _dimensions(tags),
    }


def _metadata_tool() -> str:
    executable = os.getenv("IIHS_EXIFTOOL") or shutil.which("exiftool")
    if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        raise MetadataToolUnavailable("ExifTool is not available on the server")
    return executable


def _extract(path: Path, kind: str) -> dict[str, str | None]:
    try:
        result = subprocess.run(
            [_metadata_tool(), "-j", "-api", "structformat=jsonq", "-G1", "-s", "-a", "-n", "--", str(path)],
            check=False, capture_output=True, text=True, timeout=12,
        )
        rows = json.loads(result.stdout)
        if result.returncode != 0 or not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise MetadataExtractionFailed("Media metadata could not be read")
    except MetadataExtractionFailed:
        raise
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise MetadataExtractionFailed("Media metadata could not be read") from exc
    return _normalize(rows[0], kind)


def image_metadata(path: Path, kind: str = "image") -> dict[str, str | None]:
    try:
        actual = path.resolve(strict=True)
        stat = actual.stat()
    except OSError as exc:
        raise MetadataExtractionFailed("Media source is unavailable") from exc
    if not actual.is_file():
        raise MetadataExtractionFailed("Media source is unavailable")
    key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, kind)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached
    result = _extract(actual, kind)
    with _CACHE_LOCK:
        _CACHE[key] = result
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return result
