"""
AI-stack benchmarks — REAL local models (no mocking).

Run:  python -m tests.benchmark_ai

Unlike tests/benchmark.py (hermetic), this loads the actual ML models and
measures them on CPU:
  • Multilingual embeddings   (paraphrase-multilingual-MiniLM-L12-v2, 384-dim)
  • Cross-encoder reranker     (mmarco-mMiniLMv2-L12)
  • RAG hybrid search          (ChromaDB dense + BM25 sparse + RRF + rerank)
  • Intent classification      (embedding-kNN)
  • OCR                        (EasyOCR, latin_g2 + CRAFT)

Numbers are CPU, single process. A GPU deployment would be markedly faster.
"""
import asyncio
import io
import os
import pathlib
import statistics
import tempfile
import time

# Real ML on — do NOT disable local models / Chroma.
_TMP = tempfile.mkdtemp(prefix="dxc_bench_ai_")
os.environ.pop("DISABLE_LOCAL_ML", None)
os.environ.pop("DISABLE_CHROMA", None)
os.environ["KNOWLEDGE_BASE_DIR"] = str(pathlib.Path(_TMP, "kb"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{pathlib.Path(_TMP, 'bench.db').as_posix()}"
os.environ["JWT_SECRET"] = "bench_ai_secret_key_with_at_least_32_chars"
os.environ["ENV"] = "development"
os.environ["LOG_DIR"] = str(pathlib.Path(_TMP, "logs"))


def _stats(samples_ms):
    s = sorted(samples_ms)
    n = len(s)
    return {"n": n, "mean": statistics.mean(s), "p50": statistics.median(s),
            "p95": s[min(n - 1, int(n * 0.95))], "min": s[0], "max": s[-1]}


def _row(name, s, unit="ms"):
    thr = 1000.0 / s["mean"] if s["mean"] > 0 else 0
    return (f"{name:<40} n={s['n']:>4}  mean={s['mean']:9.2f}{unit}  "
            f"p50={s['p50']:9.2f}  p95={s['p95']:9.2f}  ~{thr:,.1f} ops/s")


def bench_sync(fn, iters, warmup=2):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return _stats(samples)


async def bench_async(coro_fn, iters, warmup=2):
    for _ in range(warmup):
        await coro_fn()
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        await coro_fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return _stats(samples)


def _make_text_image() -> bytes:
    """Render a French sentence to a PNG so OCR has real text to read."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (620, 120), "white")
    d = ImageDraw.Draw(img)
    d.text((15, 20), "Incident P1 : redemarrer le service nginx", fill="black")
    d.text((15, 55), "puis verifier journalctl -u nginx -n 100", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def main():
    print("\n" + "=" * 122)
    print("DXC COPILOT — AI STACK BENCHMARKS  (REAL local models, CPU)")
    print(f"Python {os.sys.version.split()[0]}  |  torch CPU  |  models loaded from local HF/EasyOCR cache")
    print("=" * 122)

    # ── Cold-start model load times ───────────────────────────────────
    print("\n[A] MODEL LOAD (cold start, one-time)")
    print("-" * 122)
    from app.services.embedding_service import embedding_service

    t0 = time.perf_counter()
    ok = embedding_service.available            # triggers embedding model load
    emb_load = (time.perf_counter() - t0) * 1000
    print(f"{'Embedding model load':<40} {emb_load:9.1f}ms   (available={ok})")

    t0 = time.perf_counter()
    ce_ok = embedding_service.reranker_available  # triggers cross-encoder load
    ce_load = (time.perf_counter() - t0) * 1000
    print(f"{'Cross-encoder (reranker) load':<40} {ce_load:9.1f}ms   (available={ce_ok})")

    # ── Embeddings ────────────────────────────────────────────────────
    print("\n[B] EMBEDDINGS  (paraphrase-multilingual-MiniLM-L12-v2, 384-dim)")
    print("-" * 122)
    one = ["Comment redemarrer le service nginx en production ?"]
    batch8 = [f"Question technique numero {i} sur la maintenance applicative" for i in range(8)]
    batch32 = [f"Phrase de test {i} pour la vectorisation multilingue" for i in range(32)]
    print(_row("encode 1 texte court",  bench_sync(lambda: embedding_service.encode_sync(one), iters=30)))
    print(_row("encode lot de 8",       bench_sync(lambda: embedding_service.encode_sync(batch8), iters=20)))
    print(_row("encode lot de 32",      bench_sync(lambda: embedding_service.encode_sync(batch32), iters=15)))

    # ── Cross-encoder reranking ───────────────────────────────────────
    print("\n[C] CROSS-ENCODER RERANKING  (query vs N candidate docs)")
    print("-" * 122)
    q = "redemarrer un service systemd"
    docs5 = [
        "Pour redemarrer un service: systemctl restart <service>.",
        "Verifier les logs avec journalctl -u <service> -n 100.",
        "La sauvegarde de la base se fait chaque nuit a 02h.",
        "Le certificat SSL du domaine staging a expire.",
        "Augmenter la memoire du pod si OOMKilled.",
    ]
    print(_row("rerank 3 docs",  bench_sync(lambda: embedding_service.rerank_sync(q, docs5[:3]), iters=20)))
    print(_row("rerank 5 docs",  bench_sync(lambda: embedding_service.rerank_sync(q, docs5),      iters=20)))

    # ── Intent classification ─────────────────────────────────────────
    print("\n[D] INTENT CLASSIFICATION  (embedding-kNN over intent exemplars)")
    print("-" * 122)
    from app.services.intent_service import intent_service
    intent_service._build_index()   # warm the exemplar index
    print(_row("classify 1 message", bench_sync(
        lambda: intent_service.classify_sync("cree un ticket jira pour une panne critique"), iters=30)))

    # ── RAG hybrid search (end-to-end) ────────────────────────────────
    print("\n[E] RAG HYBRID SEARCH  (ChromaDB dense + BM25 + RRF + cross-encoder rerank)")
    print("-" * 122)
    from app.services.rag_service import rag_service
    stats = rag_service.get_stats()
    print(f"     Base de connaissances integree : {stats.get('total_chunks','?')} chunks, "
          f"backend={stats.get('backend','?')}")

    async def _search_rerank():
        await rag_service.search("comment redemarrer un service en panne", n_results=3, rerank=True)

    async def _search_norerank():
        await rag_service.search("comment redemarrer un service en panne", n_results=3, rerank=False)

    print(_row("search (dense+BM25, no rerank)", await bench_async(_search_norerank, iters=20)))
    print(_row("search (full, with rerank)",     await bench_async(_search_rerank,   iters=20)))

    # ── OCR ───────────────────────────────────────────────────────────
    print("\n[F] OCR  (EasyOCR — CRAFT detector + latin_g2 recognizer, CPU)")
    print("-" * 122)
    from app.services.ocr_service import ocr_service
    img = _make_text_image()

    async def _ocr():
        await ocr_service.extract_text(img, "image/png", "bench.png")

    sample = await ocr_service.extract_text(img, "image/png", "bench.png")
    print(f"     Texte extrait (echantillon) : {sample[:60]!r}")
    print(_row("OCR image 620x120 (2 lignes)", await bench_async(_ocr, iters=8, warmup=1)))

    print("\n" + "=" * 122)
    print("Notes: mesures CPU mono-processus. Le chargement des modeles (section A) est unique au demarrage.")
    print("       Une premiere requete 'chauffe' les modeles ; les latences ci-dessus sont a chaud (post warm-up).")
    print("=" * 122 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
