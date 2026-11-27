#!/usr/bin/env python3
"""Read-only Kiwoom minute-chart collector. Run outside trading hours."""
import argparse
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

DATASETS = [('kospi200', n, 'ka20005', '201', 'inds_min_pole_qry') for n in (1,3,5)] + [
    ('kodex200', 1, 'ka10080', '069500', 'stk_min_pole_chart_qry'),
    ('inverse', 1, 'ka10080', '114800', 'stk_min_pole_chart_qry')]


def collect(session, host, token, spec, start, end, root, max_pages):
    name, minutes, api, code, field = spec
    index = api == 'ka20005'
    code_field = 'inds_cd' if index else 'stk_cd'
    payload = {code_field: code, 'tic_scope': str(minutes), 'base_dt': end}
    if not index:
        payload['upd_stkpc_tp'] = '0'
    headers = {'Content-Type': 'application/json;charset=UTF-8', 'authorization': f'Bearer {token}',
               'api-id': api, 'cont-yn': 'N', 'next-key': ''}
    rows, keys = {}, set()
    skipped = 0
    repaired = 0
    reason = 'page limit'
    for page in range(1, max_pages + 1):
        for attempt in range(4):
            time.sleep(0.5 if attempt == 0 else 2 ** attempt)
            try:
                response = session.post(host.rstrip('/') + '/api/dostk/chart', headers=headers, json=payload, timeout=20)
                response.raise_for_status()
                body = response.json()
                if str(body.get('return_code')) != '0':
                    raise ValueError('API return_code=' + str(body.get('return_code')))
                if str(body.get(code_field, code)) != code or not isinstance(body.get(field), list):
                    raise ValueError('Unexpected chart response')
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == 3:
                    raise RuntimeError(f'{name}/{minutes} page {page}: {type(exc).__name__}') from None
        oldest = None
        for row in body[field]:
            stamp = str(row['cntr_tm'])
            datetime.strptime(stamp, '%Y%m%d%H%M%S')
            day = stamp[:8]
            oldest = min(oldest or day, day)
            if not start <= day <= end:
                continue
            # Index chart includes the final 15:31 record; ETF scope unchanged.
            cutoff = '153100' if index else '153000'
            if stamp[8:] > cutoff:
                skipped += 1
                continue
            prices = [int(str(row[k]).replace(',', '')) for k in ('open_pric','high_pric','low_pric','cur_prc')]
            o,h,l,c = list(map(abs, prices))
            if not (0 < l <= min(o,c) <= max(o,c) <= h):
                # Only repair a final index settlement record with a valid close
                # and OHLC fields that are either zero or equal to that close.
                # Preserve the original API row in a separate audit field.
                if index and stamp[8:] == '153100' and c > 0 and all(v in (0, c) for v in (o,h,l)):
                    row = dict(row)
                    row['_raw_ohlc'] = {k: row[k] for k in ('open_pric','high_pric','low_pric','cur_prc')}
                    for k in ('open_pric','high_pric','low_pric'):
                        row[k] = row['cur_prc']
                    repaired += 1
                    print(f'  normalized final index bar {stamp}: {prices} -> {c}', flush=True)
                else:
                    raise ValueError(f'Invalid OHLC: {name} {stamp} raw={prices} normalized={[o,h,l,c]}')
            if stamp in rows and rows[stamp] != row:
                raise ValueError(f'Conflicting duplicate: {name} {stamp}')
            rows[stamp] = row
        print(f'{name}/{minutes}m page={page} rows={len(rows)} oldest={oldest}', flush=True)
        if oldest and oldest < start:
            reason = 'requested start crossed'
            break
        cont = response.headers.get('cont-yn','N').strip().upper()
        key = response.headers.get('next-key','').strip()
        if cont != 'Y':
            reason = 'API history exhausted'
            break
        if not key or key in keys:
            raise ValueError('Missing or repeated continuation key')
        keys.add(key)
        headers.update({'cont-yn':'Y','next-key':key})
    if reason == 'page limit':
        raise RuntimeError('Page limit reached; increase --max-pages. No dataset files written.')
    folder = root / name / f'{minutes}min'
    folder.mkdir(parents=True, exist_ok=True)
    grouped = {}
    for stamp in sorted(rows):
        grouped.setdefault(stamp[:8], []).append(rows[stamp])
    for day, items in grouped.items():
        path = folder / f'{day}.json'
        # Preserve previously collected rows, refusing conflicting data.
        merged = {str(r['cntr_tm']):r for r in json.loads(path.read_text(encoding='utf-8'))} if path.exists() else {}
        for row in items:
            stamp = str(row['cntr_tm'])
            if stamp in merged and merged[stamp] != row:
                raise ValueError(f'Existing file conflict: {path} {stamp}')
            merged[stamp] = row
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps([merged[k] for k in sorted(merged)], ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)
        times = [datetime.strptime(str(r['cntr_tm']), '%Y%m%d%H%M%S') for r in items]
        gaps = sum((b-a).total_seconds() > minutes*60 for a,b in zip(times,times[1:]))
        if index and minutes == 1 and not any(str(r['cntr_tm'])[8:] == '153100' for r in items):
            print(f'  WARNING {day}: final 15:31 index bar missing; verify chart before backtest', flush=True)
        print(f'  {day}: {len(items)} bars {times[0]:%H:%M}–{times[-1]:%H:%M}, internal gaps={gaps}')
    print(f'{name}/{minutes}m: {len(grouped)} days, {reason}, post-session skipped={skipped}, final bars normalized={repaired}')
    if not grouped:
        raise RuntimeError('No bars in requested date range')
    return set(grouped)


def main():
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default=(today-timedelta(days=16)).strftime('%Y%m%d'))
    parser.add_argument('--end', default=(today-timedelta(days=1)).strftime('%Y%m%d'))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'backtest_data')
    parser.add_argument('--max-pages', type=int, default=2000)
    args = parser.parse_args()
    start,end = [datetime.strptime(v,'%Y%m%d').date() for v in (args.start,args.end)]
    if not start <= end < today or args.max_pages < 1:
        parser.error('Require start <= end < today (KST), max-pages >= 1')
    from a_config import REST_HOST
    from b_auth import get_token
    token = get_token()
    coverage = {}
    with requests.Session() as session:
        for spec in DATASETS:
            coverage[f'{spec[0]}/{spec[1]}m'] = collect(session, REST_HOST, token, spec, args.start,args.end,args.output,args.max_pages)
    common = set.intersection(*coverage.values())
    print('Common dates:', ', '.join(sorted(common)))
    for name, days in coverage.items():
        print(name, 'missing vs union:', ', '.join(sorted(set.union(*coverage.values())-days)) or 'none')
    print('Done. Coverage/gaps are diagnostics, not proof of complete trading sessions.')

if __name__ == '__main__':
    main()
