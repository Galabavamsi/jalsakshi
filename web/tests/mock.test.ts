import { describe, expect, it } from 'vitest';
import { createMockApi } from '../src/api/mock';
import { SAMPLE_ID } from '../src/api/mockSetup';
import { addDays, istDate } from '../src/lib/time';

const NOW = new Date('2026-10-09T14:00:00Z');

describe('mock: sample village', () => {
  it('the default admin sees the sample village, with 30 days and 5 complaints', async () => {
    const api = createMockApi({ now: () => NOW });
    const me = await api.getMe();
    expect(me.is_admin).toBe(true);
    expect(me.needs_setup).toBe(false);
    expect(me.village_ids).toEqual([SAMPLE_ID]);
    const today = istDate(NOW);
    const days = await api.getDays(SAMPLE_ID, addDays(today, -29), today);
    expect(days.length).toBeGreaterThanOrEqual(29);
    expect(await api.listTickets({ village_id: SAMPLE_ID })).toHaveLength(5);
    const v = await api.getVillage(SAMPLE_ID);
    expect(v.village.name).toBe('Sample village');
    expect(v.village.name_hi).toBe('नमूना गाँव');
  });
});

describe('mock: first login', () => {
  it('a new account needs setup, creates its village and adds families', async () => {
    const api = createMockApi({ now: () => NOW, user: 'new' });
    expect((await api.getMe()).needs_setup).toBe(true);
    expect(await api.listVillages()).toEqual([]);
    const [place] = await api.listPlaces('sel');
    expect(place?.name).toBe('Selud');
    const village = await api.createVillage({
      lgd_code: place?.lgd_code ?? '',
      operator: { name: 'Ramesh', phone: '98765 43210' },
    });
    const me = await api.getMe();
    expect(me.needs_setup).toBe(false);
    expect(me.village_ids).toEqual([village.id]);
    const team = await api.getTeam(village.id);
    expect(team.map((o) => [o.role, o.phone_e164])).toEqual([['NAL_JAL_MITRA', '+91XXXXXX3210']]);
    const res = await api.addHouseholdsBulk(village.id, ['9123456789', 'hello', '9123456789']);
    expect(res.added).toHaveLength(1);
    expect(res.skipped.map((s) => s.why)).toEqual(['not a mobile number', 'already added (NONE)']);
  });

  it('rejects a bad operator number', async () => {
    const api = createMockApi({ now: () => NOW, user: 'new' });
    await expect(
      api.createVillage({ name: 'X', block: 'B', district: 'D', operator: { name: 'R', phone: '123' } }),
    ).rejects.toThrow(/10-digit/);
  });

  it('caps families waiting for their consent call at 25', async () => {
    const api = createMockApi({ now: () => NOW, user: 'new' });
    const v = await api.createVillage({ name: 'Test', block: 'B', district: 'D', operator: { name: 'R', phone: '9876543210' } });
    const phones = Array.from({ length: 27 }, (_, i) => `98000000${String(i).padStart(2, '0')}`);
    const res = await api.addHouseholdsBulk(v.id, phones);
    expect(res.added).toHaveLength(25);
    expect(res.skipped).toHaveLength(2);
  });
});
