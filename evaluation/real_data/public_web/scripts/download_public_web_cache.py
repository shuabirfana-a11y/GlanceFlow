from glanceflow.evaluation.public_web_preflight import download_and_audit


def main() -> int:
    records = download_and_audit()
    for record in records:
        print(f"{record.sample_id}: {record.download_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
