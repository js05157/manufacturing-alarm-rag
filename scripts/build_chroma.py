import argparse

from config import ROOT, Settings, configure_console
from rag.embeddings import E5Encoder
from scripts.common import fingerprint, write_json
from scripts.validate_data import load_verified


def make_chunks(data, alarms, symptoms, encoder):
    chunks, skipped = [], []
    def add(text, metadata, key):
        if encoder.token_count(text) > 512:
            skipped.append({"key": key, "reason": "atomic_unit_exceeds_512_tokens"})
            return
        identifier = fingerprint([data["source_sha256"], key, text])[:32]
        chunks.append({"id": identifier, "text": text, "metadata": {"chunk_id": identifier, "source_pdf": data["source_pdf"], **metadata}})
    for alarm in alarms:
        origin = alarm["sources"][0]
        for code in alarm["codes"]:
            prefix = f"{code} {alarm['name']}\n"
            units = [(kind, item) for kind in ("description", "check_points", "actions") for item in alarm[kind]]
            # Pack whole bullet items; never combine different alarm records/codes.
            batch, batch_ids = [], []
            for kind, item in units:
                unit = f"{kind}: {item['text']}"
                if batch and encoder.token_count(prefix+"\n".join(batch+[unit])) > 450:
                    add(prefix+"\n".join(batch), {"error_code": code, "record_id": alarm["record_id"], "section": "2.5", "pdf_page": origin["pdf_page"], "printed_page": origin["printed_page"], "content_type": "alarm", "evidence_ids": "|".join(batch_ids)}, [code, alarm["record_id"], batch_ids])
                    batch, batch_ids = [], []
                batch.append(unit)
                batch_ids.append(item["id"])
            if batch:
                add(prefix+"\n".join(batch), {"error_code": code, "record_id": alarm["record_id"], "section": "2.5", "pdf_page": origin["pdf_page"], "printed_page": origin["printed_page"], "content_type": "alarm", "evidence_ids": "|".join(batch_ids)}, [code, alarm["record_id"], batch_ids])
    for symptom in symptoms:
        for row in symptom["rows"]:
            origin = row["evidence"]
            text = f"{symptom['name']}\n확인 부위: {row['area']}\n원인: {row['cause']}"
            if row["action"]:
                text += f"\n대책: {row['action']}"
            add(text, {"record_id": symptom["record_id"], "section": symptom["section"], "pdf_page": origin["pdf_page"], "printed_page": origin["printed_page"], "content_type": "symptom", "evidence_ids": row["id"]}, row["id"])
    # Page context/footnotes remain available for provenance and code-filtered
    # answers via SQLite notes, rather than embedding mixed alarm page text.
    return chunks, skipped


def main():
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings = Settings()
    data, alarms, symptoms = load_verified()
    if args.limit:
        alarms = alarms[:args.limit]
    encoder = E5Encoder(settings.embedding_model, settings.embedding_revision)
    chunks, skipped = make_chunks(data, alarms, symptoms, encoder)
    identity = encoder.identity
    corpus_id = fingerprint([identity, chunks])[:16]
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    client = chromadb.PersistentClient(path=str(settings.chroma), settings=ChromaSettings(anonymized_telemetry=False))
    # Build a new immutable collection; the manifest is published only on success.
    name = "e800_"+corpus_id
    collection = client.get_or_create_collection(name, embedding_function=None, metadata={"hnsw:space": "cosine", "source_sha256": data["source_sha256"], **identity})
    for start in range(0, len(chunks), 64):
        batch = chunks[start:start+64]
        vectors = encoder.passages([c["text"] for c in batch])
        collection.upsert(ids=[c["id"] for c in batch], embeddings=vectors, documents=[c["text"] for c in batch], metadatas=[c["metadata"] for c in batch])
    if collection.count() != len(chunks):
        raise ValueError("Chroma count mismatch")
    write_json(settings.chroma / "manifest.json", {"collection": name, "source_sha256": data["source_sha256"], "identity": identity, "chunks": len(chunks), "skipped": skipped, "initial_limit": args.limit})
    write_json(ROOT / "data/processed/chunks.json", chunks)
    print(f"Indexed {len(chunks)} chunks; skipped {len(skipped)}")


if __name__ == "__main__":
    main()
