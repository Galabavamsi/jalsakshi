/** The missed-call poster: print it and put it up where families gather. */

import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { useAsync } from '../hooks/useAsync';
import { defineMessages } from '../lib/text';
import { isSampleVillage } from '../lib/demo';
import { Button, ErrorBox, Loading, SampleBanner } from '../ui';
import { displayMissedCall } from '../lib/phones';
import QrCode from './QrCode';

const m = defineMessages({
  back: '← Back',
  print: 'Print poster',
  tip: 'Print on A4 and put it up at the Panchayat office, the school and the tap points.',
  qr: "QR code for the residents' page",
});

export function PosterPage() {
  const api = useApi();
  const { vid = '' } = useParams();
  const data = useAsync(() => Promise.all([api.getVillage(vid), api.getPublicVillage(vid).catch(() => null)]), `poster:${vid}`);
  if (data.error && !data.data) return <div className="print-page"><ErrorBox error={data.error} onRetry={data.reload} /></div>;
  if (!data.data) return <Loading />;
  const [detail, view] = data.data;
  const village = detail.village;
  const number = displayMissedCall(view?.missed_call_number);
  const url = `${window.location.origin}/v/${encodeURIComponent(vid)}?lang=hi`;

  return (
    <div className="print-page poster">
      <div className="actions no-print">
        <Link className="btn" to={`/villages/${encodeURIComponent(vid)}/more`}>{m.back}</Link>
        <Button variant="primary" onClick={() => window.print()}>{m.print}</Button>
      </div>
      <p className="note no-print">{m.tip}</p>
      {isSampleVillage(vid) && <SampleBanner />}
      <h1 lang="hi">जल साक्षी</h1>
      <p className="big" lang="hi">{village.name_hi || village.name} — क्या आज नल में पानी आया?</p>
      <p lang="hi" style={{ fontSize: '1.4rem' }}>जुड़ने के लिए इस नंबर पर मिस्ड कॉल दें:</p>
      <p className="number">{number}</p>
      <p lang="hi">
        हम आपको वापस कॉल करेंगे। जुड़ने के लिए 1 दबाएँ। फिर हर शाम एक छोटी कॉल आएगी:
        <br />
        <b>1</b> = पानी आया · <b>2</b> = पानी नहीं आया · <b>3</b> = थोड़ा पानी
      </p>
      <p lang="hi">कोई पैसा नहीं लगता। हम आपको तुरंत वापस कॉल करते हैं।</p>
      <QrCode value={url} label={m.qr} />
      <p lang="hi" className="note">गाँव का पानी का रिकॉर्ड देखने के लिए QR स्कैन करें</p>
    </div>
  );
}
