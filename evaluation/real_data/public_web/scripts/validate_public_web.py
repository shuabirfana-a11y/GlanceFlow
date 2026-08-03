from glanceflow.evaluation.public_web import validate_metadata


if __name__ == "__main__":
    rows, annotations = validate_metadata()
    print(f"validated metadata: {len(rows)} samples, {len(annotations)} annotations")
