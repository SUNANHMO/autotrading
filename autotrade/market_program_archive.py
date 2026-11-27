"""Read-only KRX market program tick archive (ka90005, current day only)."""
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

FIELDS = ('dfrt_trde_netprps', 'ndiffpro_trde_netprps', 'all_netprps')


def archive_market_program(session, host, token, root, max_pages=2000):
    day = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d')
    if datetime.strptime(day, '%Y%m%d').weekday() >= 5 or not token:
        raise ValueError('Trading weekday and token required')
    payload = dict(date=day, amt_qty_tp='1', mrkt_tp='P00101', min_tic_tp='0', stex_tp='1')
    headers = {'authorization': f'Bearer {token}', 'Content-Type': 'application/json;charset=UTF-8',
               'api-id': 'ka90005', 'cont-yn': 'N', 'next-key': ''}
    rows, keys = {}, set()
    for page in range(1, max_pages + 1):
        for attempt in range(4):
            time.sleep(0.5 if attempt == 0 else 2 ** attempt)
            try:
                response = session.post(host.rstrip('/') + '/api/dostk/mrkcond', headers=headers, json=payload, timeout=20)
                response.raise_for_status()
                body = response.json()
                if str(body.get('return_code')) != '0' or not isinstance(body.get('prm_trde_trnsn'), list):
                    raise ValueError('Unexpected ka90005 response')
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise RuntimeError(f'ka90005 page {page} failed') from None
        for row in body['prm_trde_trnsn']:
            stamp = str(row['cntr_tm']).strip()
            if len(stamp) != 6 or not stamp.isdigit():
                raise ValueError('Invalid tick time')
            datetime.strptime(stamp, '%H%M%S')
            for field in FIELDS:
                int(str(row[field]).replace(',', ''))
            # Preserve distinct ticks sharing a timestamp, and raw API fields.
            rows.setdefault(json.dumps(row, sort_keys=True, ensure_ascii=False), row)
        print(f'ka90005 page={page} rows={len(rows)}', flush=True)
        if response.headers.get('cont-yn', 'N').strip().upper() != 'Y':
            break
        key = response.headers.get('next-key', '').strip()
        if not key or key in keys:
            raise ValueError('Missing or repeated continuation key')
        keys.add(key)
        headers.update({'cont-yn': 'Y', 'next-key': key})
    else:
        raise RuntimeError('ka90005 page limit reached')
    if not rows or datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d') != day:
        raise ValueError('Empty response or date changed')
    folder = Path(root) / 'kospi_program' / 'tick'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{day}.json'
    items = sorted(rows.values(), key=lambda r: str(r['cntr_tm']))
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        old_keys = {json.dumps(r, sort_keys=True, ensure_ascii=False) for r in old}
        if not old_keys.issubset(rows):
            raise ValueError('Existing archive contains missing or changed ticks; preserved')
        if len(old_keys) == len(rows):
            return path, len(old), False
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder, delete=False) as f:
            tmp = f.name
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return path, len(items), True


def collect_today(token, root=None, max_pages=2000):
    from a_config import REST_HOST
    with requests.Session() as session:
        result = archive_market_program(session, REST_HOST, token,
                                        root or Path(__file__).resolve().parent / 'backtest_data', max_pages)
    print(f'[코스피 프로그램 저장] {result[0]}: {result[1]}건, 갱신={result[2]}', flush=True)
    return result
