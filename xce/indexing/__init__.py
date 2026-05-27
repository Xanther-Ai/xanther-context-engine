"""Indexing subpackage — orchestrator, doc generation, embeddings, summarization."""

from xce.indexing.doc_generator import DocGenerator
from xce.indexing.embedding import EmbeddingService
from xce.indexing.indexer import IndexResult, index_repository
from xce.indexing.summarizer import ContextSummarizer

__all__ = [
    "DocGenerator",
    "EmbeddingService",
    "IndexResult",
    "index_repository",
    "ContextSummarizer",
]
