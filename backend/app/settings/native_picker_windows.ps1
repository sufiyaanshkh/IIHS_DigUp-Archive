$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class NativeFolders
{
    [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    private class FileOpenDialog { }

    [ComImport, Guid("D57C7288-D4AD-4768-BE02-9D969532D960"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileOpenDialog
    {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes();
        void SetFileTypeIndex();
        void GetFileTypeIndex();
        void Advise();
        void Unadvise();
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder();
        void SetFolder();
        void GetFolder();
        void GetCurrentSelection();
        void SetFileName();
        void GetFileName();
        void SetTitle();
        void SetOkButtonLabel();
        void SetFileNameLabel();
        void GetResult();
        void AddPlace();
        void SetDefaultExtension();
        void Close();
        void SetClientGuid();
        void ClearClientData();
        void SetFilter();
        void GetResults(out IShellItemArray items);
    }

    [ComImport, Guid("B63EA76D-1F85-456F-A19C-48159EFA858B"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItemArray
    {
        void BindToHandler();
        void GetPropertyStore();
        void GetPropertyDescriptionList();
        void GetAttributes();
        void GetCount(out uint count);
        void GetItemAt(uint index, out IShellItem item);
        void EnumItems();
    }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler();
        void GetParent();
        void GetDisplayName(uint nameType, out IntPtr name);
        void GetAttributes();
        void Compare();
    }

    public static string[] Choose()
    {
        var dialog = (IFileOpenDialog)new FileOpenDialog();
        try
        {
            uint options;
            dialog.GetOptions(out options);
            dialog.SetOptions(options | 0x20u | 0x40u | 0x200u | 0x800u);
            int status = dialog.Show(IntPtr.Zero);
            if (unchecked((uint)status) == 0x800704C7u) return new string[0];
            Marshal.ThrowExceptionForHR(status);
            IShellItemArray items;
            dialog.GetResults(out items);
            try
            {
                uint count;
                items.GetCount(out count);
                var paths = new List<string>();
                for (uint i = 0; i < count; i++)
                {
                    IShellItem item;
                    items.GetItemAt(i, out item);
                    try
                    {
                        IntPtr name;
                        item.GetDisplayName(0x80058000u, out name);
                        try { paths.Add(Marshal.PtrToStringUni(name)); }
                        finally { Marshal.FreeCoTaskMem(name); }
                    }
                    finally { Marshal.ReleaseComObject(item); }
                }
                return paths.ToArray();
            }
            finally { Marshal.ReleaseComObject(items); }
        }
        finally { Marshal.ReleaseComObject(dialog); }
    }
}
'@
$paths = [NativeFolders]::Choose()
[Console]::Out.Write((ConvertTo-Json -InputObject @($paths) -Compress))
