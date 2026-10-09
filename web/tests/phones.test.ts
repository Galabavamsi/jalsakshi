import { describe, expect, it } from 'vitest';
import { displayMissedCall, maskMobile, normaliseMobile, parsePhoneList, shortMasked } from '../src/lib/phones';

describe('normaliseMobile', () => {
  it('accepts common Indian spellings', () => {
    expect(normaliseMobile('98765 43210')).toBe('+919876543210');
    expect(normaliseMobile('+91-98765-43210')).toBe('+919876543210');
    expect(normaliseMobile('09876543210')).toBe('+919876543210');
    expect(normaliseMobile('919876543210')).toBe('+919876543210');
  });
  it('rejects landlines and junk', () => {
    expect(normaliseMobile('022 2345 678')).toBeNull();
    expect(normaliseMobile('12345')).toBeNull();
    expect(normaliseMobile('5876543210')).toBeNull();
    expect(normaliseMobile('ramesh')).toBeNull();
  });
});

describe('parsePhoneList', () => {
  it('splits lines, commas and semicolons, de-duplicates and keeps bad lines', () => {
    const r = parsePhoneList('98765 43210\n\n91234-56789, 9876543210; hello\n12');
    expect(r.valid).toEqual(['+919876543210', '+919123456789']);
    expect(r.invalid).toEqual(['hello', '12']);
  });
});

describe('masking and display', () => {
  it('masks like the API and shows the last four digits', () => {
    expect(maskMobile('+919876543210')).toBe('+91XXXXXX3210');
    expect(shortMasked('+91XXXXXX3210')).toBe('•••• 3210');
  });
  it('formats the missed-call number', () => {
    expect(displayMissedCall('+918064260325')).toBe('080 6426 0325');
    expect(displayMissedCall(null)).toBe('080 6426 0325');
  });
});
