"""Phase 0.5: read existing Meridian statistics from a DB copy.

Usage: python3 scripts/dev_compare_stats.py /tmp/meridian_val/ha.db

Read-only. Prints each meridian statistic's unit and last cumulative sum
(the continuity baseline the integration must continue from).
"""

import sqlite3
import sys
from datetime import datetime, timezone


def main(db_path: str) -> None:
    con = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT id, statistic_id, unit_of_measurement "
        "FROM statistics_meta WHERE statistic_id LIKE 'meridian_energy:%' ORDER BY statistic_id"
    )
    metas = cur.fetchall()
    if not metas:
        print("No meridian_energy statistics found in this DB.")
        return
    print(f"{'statistic_id':<40} {'unit':<6} {'last_sum':>14} last_start(UTC)")
    for meta_id, sid, unit in metas:
        cur.execute(
            "SELECT start_ts, sum FROM statistics WHERE metadata_id=? "
            "ORDER BY start_ts DESC LIMIT 1",
            (meta_id,),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            last_start = datetime.fromtimestamp(row[0], tz=timezone.utc).isoformat()
            last_sum = row[1]
        else:
            last_start, last_sum = "-", None
        print(f"{sid:<40} {unit or '-':<6} {str(last_sum):>14} {last_start}")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 scripts/dev_compare_stats.py <path-to-ha.db>")
        raise SystemExit(2)
    main(sys.argv[1])
