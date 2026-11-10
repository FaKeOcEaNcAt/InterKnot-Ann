import argparse
import os
import tempfile
from datetime import datetime
from pathlib import Path

from scripts import official
from scripts.bilibili import collect, three_months_ago
from scripts.model import CST, DATA, ID, MAX_STORE, ROOT, Invalid, date, decode, encoded, load_store, require, validate_store


def merge(store, incoming, first_ids, now):
    merged = {item["id"]: item for item in store["items"]}
    active_sources = {item["source"] for item in incoming.values()}
    for identifier, item in list(merged.items()):
        if item["source"] in active_sources and item["is_pinned"] and identifier not in first_ids:
            merged[identifier] = dict(item, is_pinned=False)
    for identifier, item in incoming.items():
        item = dict(item, is_pinned=identifier in first_ids and item["is_pinned"])
        old = merged.get(identifier)
        if old:
            old_date = date(old["published_at"])
            new_date = date(item["published_at"])
            require(old_date == new_date or (old["ingest"] == "editorial"
                    and old_date == new_date.replace(second=0)), "publication timestamp conflict")
            changed = old["content_hash"] != item["content_hash"]
            if old["ingest"] == "editorial":
                item = dict(item, title=old["title"], category=old["category"],
                            summary=old["summary"], content=old["content"])
            elif not changed and old["source"] == "bilibili":
                item = dict(old, is_pinned=item["is_pinned"])
            item = dict(item, updated_at=old["updated_at"])
            if changed and old["ingest"] == "feed":
                item["updated_at"] = max(date(now), date(old["updated_at"] or old["published_at"])).isoformat()
            else:
                item["images"] = old["images"]
        merged[identifier] = item
    if merged == {item["id"]: item for item in store["items"]}:
        return store
    return validate_store({
        "schema": 1, "last_changed_sync": now,
        "items": sorted(merged.values(), key=lambda item: (date(item["published_at"]), item["id"]), reverse=True),
    })


def save(path, value):
    data = encoded(value)
    require(len(data) <= MAX_STORE, "archive exceeds byte limit")
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".archive-")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def settings():
    config = decode((ROOT / "config" / "sources.json").read_bytes())
    require(isinstance(config, dict) and config.get("adapter") in ("bilibili-opus", "hoyoverse-official"),
            "unknown adapter")
    count = config.get("page_limit")
    interval = config.get("interval_seconds")
    excluded = config.get("exclude_ids")
    require(type(count) is int and 1 <= count <= 30, "invalid page_limit")
    require(type(interval) is int and 2 <= interval <= 60, "invalid interval_seconds")
    require(isinstance(excluded, list) and all(isinstance(i, str) and ID.fullmatch(i) for i in excluded),
            "invalid exclude_ids")
    return config["adapter"], count, interval, set(excluded)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="validate live pages without changing the archive")
    args = parser.parse_args()
    try:
        store = load_store()
        adapter, count, interval, excluded = settings()
        current = datetime.now(CST)
        count = min(count, 2) if args.probe else count
        cutoff = three_months_ago(current)
        if adapter == "hoyoverse-official":
            incoming, first_ids = official.collect(count, interval, excluded, cutoff, current)
        else:
            incoming, first_ids = collect(count, interval, excluded, cutoff)
        now = current.isoformat(timespec="seconds")
        if args.probe:
            print("{} live probe succeeded at {}".format(adapter, now))
            return 0
        updated = merge(store, incoming, first_ids, now)
        if updated is store:
            print("{} sync succeeded at {}; no archive changes".format(adapter, now))
        else:
            save(DATA, updated)
            print("{} sync succeeded at {}; {} archived records".format(adapter, now, len(updated["items"])))
        return 0
    except Invalid as error:
        print("Sync failed; archive preserved: " + str(error))
    except (ValueError, OSError, OverflowError, RecursionError) as error:
        print("Sync failed; archive preserved: " + type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
