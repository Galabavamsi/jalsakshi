import { describe, expect, it } from 'vitest';
import { createMockApi } from '../src/api/mock';
import { MOCK_REGISTER_ROWS } from '../src/api/mockSetup';
import { areaList, groupByArea, reporterAreaText } from '../src/lib/households';
import { fitSize } from '../src/lib/image';
import { EMPTY_FORM, toPanchayatRequest, validatePanchayat, type PanchayatForm } from '../src/pages/Admin';
import { reviewToFamilies, toReview } from '../src/pages/BulkAdd';

const place = { lgd_code: '442571', name: 'Kopedih', block: 'Patan', district: 'Durg' };
const good: PanchayatForm = { ...EMPTY_FORM, place, operatorPhone: '98765 43210', username: 'kopedih-gp' };

describe('Set up a Panchayat form', () => {
  it('accepts a complete form and builds the request', () => {
    expect(validatePanchayat(good)).toEqual([]);
    const req = toPanchayatRequest({ ...good, languages: ['hne', 'hi'] });
    expect(req.village).toEqual({ lgd_code: '442571' });
    expect(req.languages).toEqual(['hne', 'hi']);
    expect(req.sarpanch).toBeUndefined();
    expect(req.temporary_password).toBeUndefined();
  });

  it('names every problem in plain words', () => {
    const errors = validatePanchayat({
      ...EMPTY_FORM,
      languages: [],
      operatorPhone: '12345',
      sarpanchName: 'Sita',
      username: 'A',
      password: 'short',
    });
    expect(errors).toHaveLength(6);
    expect(errors.join(' ')).toMatch(/Choose the village/);
    expect(errors.join(' ')).toMatch(/sarpanch/);
  });

  it('needs name, block and district for a village typed in', () => {
    expect(validatePanchayat({ ...good, manual: true, name: 'Navagaon' })[0]).toMatch(/block and district/);
  });
});

describe('Photo of a register', () => {
  it('starts with bad numbers unticked and never sends them', () => {
    const review = toReview(MOCK_REGISTER_ROWS);
    expect(review.map((r) => r.include)).toEqual([true, true, false, true]);
    const families = reviewToFamilies(review);
    expect(families).toHaveLength(3);
    expect(families.some((f) => f.name === 'Gita Bai')).toBe(false);
    // Ticking a row whose number is still bad does not send it either.
    expect(reviewToFamilies(review.map((r) => ({ ...r, include: true })))).toHaveLength(3);
    expect(families[2]?.area).toBeNull();
  });

  it('adds families with their name and area (mock)', async () => {
    const api = createMockApi();
    const rows = (await api.readRegisterPhoto('sample-village', 'abc', 'image/jpeg')).rows;
    const res = await api.addFamilies('sample-village', reviewToFamilies(toReview(rows)));
    expect(res.added.map((h) => h.hamlet)).toEqual(['Thakur para', 'Thakur para', null]);
    expect(res.added[0]?.display_name).toBe('Ramesh Sahu');
  });

  it('calls a waiting family again, but not one that already agreed (mock)', async () => {
    const api = createMockApi();
    const rows = (await api.readRegisterPhoto('sample-village', 'abc', 'image/jpeg')).rows;
    const [first] = (await api.addFamilies('sample-village', reviewToFamilies(toReview(rows)))).added;
    await expect(api.callAgain('sample-village', first!.id)).resolves.toEqual({ call: 'queued' });
    await expect(api.callAgain('sample-village', 'ghost')).rejects.toThrow();
  });

  it('shrinks big photos to 1600 px on the longest side', () => {
    expect(fitSize(4000, 3000)).toEqual({ width: 1600, height: 1200 });
    expect(fitSize(800, 600)).toEqual({ width: 800, height: 600 });
  });
});

describe('Areas', () => {
  const hh = [
    { id: 'a', hamlet: 'Thakur para' },
    { id: 'b', hamlet: null },
    { id: 'c', hamlet: 'Schoolpara' },
    { id: 'd', hamlet: 'Thakur para ' },
  ];
  it('lists, groups and names the areas of reporters', () => {
    expect(areaList(hh)).toEqual(['Schoolpara', 'Thakur para']);
    expect(groupByArea(hh).map((g) => [g.area, g.items.length])).toEqual([
      ['Schoolpara', 1],
      ['Thakur para', 2],
      [null, 1],
    ]);
    expect(reporterAreaText(['a', 'c'], hh)).toBe('Schoolpara, Thakur para');
    expect(reporterAreaText(['b'], hh)).toBe('Area not given');
  });
});

describe('Settings and languages (mock)', () => {
  it('saves call languages with the default first and rejects unknown ones', async () => {
    const api = createMockApi();
    expect((await api.listLanguages()).filter((l) => l.ready).map((l) => l.code)).toEqual(['hi', 'hne']);
    const v = await api.saveVillageSettings('sample-village', { languages: ['hne', 'hi'], checkin_local_time: '18:30' });
    expect(v.languages).toEqual(['hne', 'hi']);
    expect(v.checkin_local_time).toBe('18:30');
    await expect(api.saveVillageSettings('sample-village', { languages: ['xx'] })).rejects.toThrow(/unknown call language/);
  });

  it('only the team can create a Panchayat', async () => {
    const secretary = createMockApi({ user: 'member' });
    await expect(
      secretary.createPanchayat({
        username: 'abc',
        village: { lgd_code: '442571' },
        languages: ['hi'],
        operator: { name: '', phone: '9876543210' },
      }),
    ).rejects.toThrow(/JalSakshi team/);
  });
});
