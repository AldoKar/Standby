// "Link glasses": the QR the Even app scans to open Standby on the glasses (same as `evenhub qr --url ...`,
// which is just this page's address as a QR code). No terminal needed.
// - Local (npm run dev): the laptop's LAN address, found by Vite at startup (__LAN_URL__), since the phone
//   can't open "localhost". Same Wi-Fi as the laptop.
// - Hosted (production): this page's own address, e.g. https://glasses.149.28.76.19.sslip.io
// The QR is for testing on the glasses; real users install the .ehpk from Even Hub.
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'

const LOCAL_HOSTS = /^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?)$/

/** The address the phone should open. */
function linkUrl(): string {
  const fromEnv = import.meta.env.VITE_LINK_URL as string | undefined
  if (fromEnv) return fromEnv
  if (LOCAL_HOSTS.test(location.hostname) && __LAN_URL__) return __LAN_URL__
  return `${location.origin}${location.pathname}`
}

/** True when the QR would point at this machine only (no LAN address found): the phone can't open it. */
const unreachable = (url: string) => LOCAL_HOSTS.test(new URL(url).hostname)

export function LinkGlasses() {
  const dialog = useRef<HTMLDialogElement>(null)
  const [url] = useState(linkUrl)
  const [qr, setQr] = useState('')

  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 240, errorCorrectionLevel: 'M' })
      .then(setQr)
      .catch(() => setQr(''))
  }, [url])

  return (
    <>
      <button type="button" className="btn link-btn" onClick={() => dialog.current?.showModal()}>
        Link glasses
      </button>
      <dialog ref={dialog} className="link-dialog" aria-labelledby="link-title" onClick={(e) => e.target === e.currentTarget && dialog.current?.close()}>
        <h2 id="link-title">Link your glasses</h2>
        <p>Scan with the Even app on your phone to open Standby on your G2.</p>
        {qr ? <img className="link-qr" src={qr} alt={`QR code for ${url}`} width={240} height={240} /> : <p>Couldn't draw the QR.</p>}
        <code className="link-url">{url}</code>
        {unreachable(url) ? (
          <p className="link-note">This address only works on this computer. Open this page with your laptop's IP instead of localhost.</p>
        ) : import.meta.env.DEV ? (
          <p className="link-note">Your phone must be on the same Wi-Fi as this laptop.</p>
        ) : null}
        <button type="button" className="btn btn-primary link-close" onClick={() => dialog.current?.close()}>
          Close
        </button>
      </dialog>
    </>
  )
}
