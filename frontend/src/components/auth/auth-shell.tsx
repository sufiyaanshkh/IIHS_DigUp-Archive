import Image from "next/image";

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="auth-page">
      <section className="auth-frame" aria-label="IIHS Media Archive account access">
        <aside className="auth-brand-panel">
          <div className="auth-brand-lockup">
            <Image src="/IIHS-logo.svg" alt="IIHS" width={58} height={42} priority />
            <span>Media Archive</span>
          </div>
          <div className="auth-brand-copy">
            <p className="auth-kicker">IIHS · RESEARCH COLLECTIONS</p>
            <h1>Find the material behind the work.</h1>
            <p>One place for the images, documents, recordings and moving footage that support IIHS research.</p>
          </div>
          <div className="auth-sample-strip" aria-label="Examples of archive materials">
            <div className="auth-sample auth-sample-photo"><Image src="/demo/img-4133.jpg" alt="Sample image from the archive" fill sizes="(max-width: 760px) 100vw, 34vw" /></div>
            <div className="auth-sample auth-sample-document"><Image src="/demo/lease-page-4.jpg" alt="Sample document page from the archive" fill sizes="(max-width: 760px) 100vw, 34vw" /></div>
            <div className="auth-sample auth-sample-photo auth-sample-third"><Image src="/demo/img-4128.jpg" alt="Another sample image from the archive" fill sizes="(max-width: 760px) 100vw, 34vw" /></div>
          </div>
          <div className="auth-brand-foot"><span className="auth-foot-rule" />A considered way into the collection</div>
        </aside>
        <section className="auth-form-panel">
          <div className="auth-mobile-brand"><Image src="/IIHS-logo.svg" alt="IIHS" width={42} height={30} /><span>Media Archive</span></div>
          {children}
          <p className="auth-privacy-note">Access is intended for authorised IIHS colleagues.</p>
        </section>
      </section>
      <footer className="auth-page-footer"><span>IIHS Media Archive</span><span>Research materials, thoughtfully connected.</span></footer>
    </main>
  );
}
