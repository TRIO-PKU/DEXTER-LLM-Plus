#!/usr/bin/env python3
"""
RAG Core Module - Refactored for core search functionality.
"""

import json
import os
from modelscope import snapshot_download
from typing import List, Dict, Any, Tuple, TYPE_CHECKING, Optional
import re

# Type checking imports
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    import faiss
    import jieba
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

# --- Library Availability Checks ---
HAS_ADVANCED_RAG = False
SentenceTransformer = None
faiss = None
np = None
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    import faiss  # type: ignore
    import numpy as np  # type: ignore

    HAS_ADVANCED_RAG = True
    print("[RAG] Using advanced RAG libraries: sentence-transformers + faiss")
except ImportError:
    print(
        "[RAG] Advanced RAG libraries not installed. Falling back to simpler methods."
    )

HAS_JIEBA = False
jieba = None
try:
    import jieba  # type: ignore

    HAS_JIEBA = True
except ImportError:
    print("[RAG] jieba not installed, using basic tokenization.")

HAS_SKLEARN = False
TfidfVectorizer = None
cosine_similarity = None
try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

    # numpy might be imported by advanced rag, but sklearn needs it too
    if np is None:
        import numpy as np  # type: ignore
    HAS_SKLEARN = True
    print("[RAG] Using scikit-learn as a fallback.")
except ImportError:
    print("[RAG] scikit-learn not installed.")


def get_local_hf_model(model_name, local_dir):
    """
    检查本地是否有模型，没有则下载，有则直接加载。
    用于 transformers/ sentence-transformers 等 from_pretrained 接口。
    """
    if not os.path.exists(local_dir) or not os.listdir(local_dir):
        print(f"[RAG] 本地未找到模型，正在从下载 {model_name} ...")
        snapshot_download(repo_id=model_name, local_dir=local_dir)
    else:
        print(f"[RAG] 已检测到本地模型，直接加载：{local_dir}")
    return local_dir


# --- Base Retriever Class ---


class BaseRetriever:
    """Abstract base class for all retrievers."""

    def build_index(self, texts: List[str]) -> None:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 3) -> Tuple[List[int], List[float]]:
        raise NotImplementedError

    def is_ready(self) -> bool:
        return False


# --- Retriever Implementations ---


class AdvancedRetriever(BaseRetriever):
    """Retriever based on sentence-transformers and faiss."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self.model_name = model_name
        self.model: Optional[Any] = None
        self.index: Optional[Any] = None
        self.texts: List[str] = []
        self._init_model()

    def _init_model(self):
        if not HAS_ADVANCED_RAG or not SentenceTransformer:
            print("[RAG] Cannot initialize AdvancedRetriever: missing libraries.")
            return
        try:
            local_dir = os.path.join(
                os.path.expanduser("~"),
                ".cache/hf_models",
                self.model_name.replace("/", "__"),
            )
            model_path = get_local_hf_model(self.model_name, local_dir)
            print(f"[RAG] Loading embedding model: {model_path} ...")
            self.model = SentenceTransformer(model_path)
            print(f"[RAG] Successfully loaded model: {self.model_name}")
        except Exception as e:
            print(f"[RAG] Failed to load model {self.model_name}: {e}")
            self.model = None

    def build_index(self, texts: List[str]) -> None:
        if not self.model or not texts or not HAS_ADVANCED_RAG or not faiss or not np:
            return
        self.texts = texts
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        faiss.normalize_L2(embeddings)
        if self.index is not None:
            self.index.add(embeddings.astype(np.float32))
            print(f"[RAG] Built faiss index with {len(texts)} documents.")

    def search(self, query: str, top_k: int = 3) -> Tuple[List[int], List[float]]:
        if (
            not self.is_ready()
            or not query.strip()
            or not self.model
            or not self.index
            or not faiss
            or not np
        ):
            return [], []
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)
        scores, indices = self.index.search(query_embedding.astype(np.float32), top_k)
        return indices[0].tolist(), scores[0].tolist()

    def is_ready(self) -> bool:
        return self.model is not None and self.index is not None


class SklearnRetriever(BaseRetriever):
    """Retriever based on scikit-learn's TF-IDF."""

    def __init__(self):
        self.vectorizer: Optional[Any] = None
        self.tfidf_matrix: Optional[Any] = None  # The type is sparse matrix
        self.texts: List[str] = []

    def _preprocess_text(self, text: str) -> str:
        text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", " ", str(text))
        if HAS_JIEBA and jieba:
            return " ".join(jieba.lcut(text))
        return text.lower()

    def build_index(self, texts: List[str]) -> None:
        if not HAS_SKLEARN or not TfidfVectorizer:
            return
        self.texts = texts
        processed_texts = [self._preprocess_text(text) for text in texts]
        self.vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
        if self.vectorizer is not None:
            self.tfidf_matrix = self.vectorizer.fit_transform(processed_texts)
            if self.tfidf_matrix is not None:
                print(f"[RAG] Built TF-IDF index with shape: {self.tfidf_matrix.shape}")

    def search(self, query: str, top_k: int = 3) -> Tuple[List[int], List[float]]:
        if (
            not self.is_ready()
            or not query.strip()
            or not self.vectorizer
            or self.tfidf_matrix is None
            or not cosine_similarity
            or not np
        ):
            return [], []
        processed_query = self._preprocess_text(query)
        query_vector = self.vectorizer.transform([processed_query])
        similarities = cosine_similarity(query_vector, self.tfidf_matrix).flatten()
        top_indices = np.argsort(similarities)[::-1][:top_k]
        return top_indices.tolist(), similarities[top_indices].tolist()

    def is_ready(self) -> bool:
        return self.vectorizer is not None and self.tfidf_matrix is not None


class SimpleRetriever(BaseRetriever):
    """Simple keyword-based retriever."""

    def __init__(self):
        self.texts: List[str] = []

    def build_index(self, texts: List[str]) -> None:
        self.texts = [self._preprocess_text(text) for text in texts]
        print(f"[RAG] Built simple index with {len(texts)} documents.")

    def _preprocess_text(self, text: str) -> str:
        text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", " ", str(text).lower())
        return re.sub(r"\s+", " ", text).strip()

    def _calculate_similarity(self, query: str, text: str) -> float:
        query_words = set(query.split())
        text_words = set(text.split())
        if not query_words or not text_words:
            return 0.0
        return len(query_words.intersection(text_words)) / len(query_words)

    def search(self, query: str, top_k: int = 3) -> Tuple[List[int], List[float]]:
        if not self.is_ready() or not query.strip():
            return [], []
        processed_query = self._preprocess_text(query)
        scores = [
            (i, self._calculate_similarity(processed_query, text))
            for i, text in enumerate(self.texts)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        top_scores = scores[:top_k]
        return [i for i, s in top_scores], [s for i, s in top_scores]

    def is_ready(self) -> bool:
        return bool(self.texts)


# --- Main Knowledge Base Class ---


class RAGKnowledgeBase:
    """A simplified RAG knowledge base for core search functionality."""

    def __init__(
        self,
        knowledge_file_path: str,
        retriever_type: str = "auto",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self.knowledge_file_path = knowledge_file_path
        self.knowledge_data: List[str] = []
        self.retriever: Optional[BaseRetriever] = None

        self._init_retriever(retriever_type, embedding_model)
        self.load_knowledge_base()
        self.build_index()

    def _init_retriever(self, retriever_type: str, embedding_model: str):
        if retriever_type == "auto":
            if HAS_ADVANCED_RAG:
                self.retriever = AdvancedRetriever(embedding_model)
            elif HAS_SKLEARN:
                self.retriever = SklearnRetriever()
            else:
                self.retriever = SimpleRetriever()
        elif retriever_type == "advanced":
            if not HAS_ADVANCED_RAG:
                raise ImportError(
                    "Advanced RAG libraries (sentence-transformers, faiss) are not installed."
                )
            self.retriever = AdvancedRetriever(embedding_model)
        elif retriever_type == "sklearn":
            if not HAS_SKLEARN:
                raise ImportError("scikit-learn is not installed.")
            self.retriever = SklearnRetriever()
        elif retriever_type == "simple":
            self.retriever = SimpleRetriever()
        else:
            raise ValueError(f"Unknown retriever type: {retriever_type}")
        if self.retriever:
            print(f"[RAG] Initialized retriever: {self.retriever.__class__.__name__}")

    def load_knowledge_base(self) -> None:
        try:
            with open(self.knowledge_file_path, "r", encoding="utf-8") as f:
                self.knowledge_data = json.load(f)
            print(
                f"[RAG] Loaded {len(self.knowledge_data)} items from {self.knowledge_file_path}"
            )
        except Exception as e:
            print(f"[RAG] Error loading knowledge base: {e}")

    def build_index(self) -> None:
        if not self.knowledge_data or not self.retriever:
            return
        texts = [item for item in self.knowledge_data]
        self.retriever.build_index(texts)

    def search(
        self, query: str, top_k: int = 3, similarity_threshold: float = 0.1
    ) -> List[str]:
        if not self.retriever or not self.retriever.is_ready() or not query.strip():
            return []

        indices, scores = self.retriever.search(query, top_k=top_k)

        results = []
        for idx, score in zip(indices, scores):
            if score >= similarity_threshold:
                results.append(self.knowledge_data[idx])

        print(
            f"[RAG] Found {len(results)} relevant results for query: '{query[:50]}...'"
        )
        return results

    def reload_knowledge_base(self) -> None:
        """Reloads the knowledge base from the file and rebuilds the index."""
        print("[RAG] Reloading knowledge base...")
        self.load_knowledge_base()
        self.build_index()


if __name__ == "__main__":
    print("[RAG] Running basic tests...")
    # 测试数据
    test_texts = [
        "Alkane gas flames involve hazardous combustion scenarios. To manage such situations effectively, a combination of skills is required, including inspecting the situation to gather critical information about the source of the flame and surrounding risks. Controlling the flow of alkane gas by operating valves or switches reduces fuel supply. Fire suppression techniques like liquid spray using water or foam help cool the flames and block oxygen. Monitoring ensures that the fire is fully extinguished, and cleanup addresses residual hazards.",
        "High-temperature liquid flames are highly dangerous due to their intense heat and fluidity, which can lead to rapid spread and secondary hazards. The response involves inspecting the scene to assess the fire's extent and potential spread. Solid sprays (such as powder or dry ice) suppress flames and reduce temperatures. Cleanup removes residual dangers, while throwing fire-extinguishing bombs or laying asbestos felt provides additional suppression and isolation. Continuous monitoring ensures complete control over the situation.",
        "Metal oxide fires are challenging to extinguish due to high reaction temperatures and the risk of re-ignition. These fires require specialized suppression techniques, such as applying solid sprays (e.g., powder) and liquid sprays (e.g., ammonium hydroxide or calcium hydroxide) to suppress the chemical reaction. Laying activated carbon or using inert gases helps isolate and control the hazard. Monitoring is crucial to prevent re-ignition.",
        "High-voltage electrical flames pose significant risks due to electric shock hazards and rapid fire spread. Initial actions include cutting off power by operating switches to reduce danger. Appropriate extinguishing methods involve liquid sprays (e.g., foam or water), building fire dikes to contain the fire, and using inert gas sprays for further suppression. Inspection and monitoring ensure safety and complete extinguishment.",
        "Trapped persons require urgent rescue to avoid injury or loss of life. The process includes inspecting the environment to locate and evaluate the condition of the victim, cleaning up debris or hazards, performing rescue operations, and transporting the individual to a safe location. Coordination is essential to ensure the safety of both victims and rescuers.",
        "Poisoned individuals need immediate intervention to mitigate harm from toxic exposure. Actions involve inspecting the scenario to identify the toxin and the person’s condition, administering antidotes or oxygen, and monitoring recovery. Rescue efforts may also include relocating the person to a safer environment and providing ongoing support until full recovery.",
        "Hydrogen sulfide leakage poses severe health and explosion risks. Immediate containment measures, such as building fire dikes, help prevent spread. Controlled ignition of the gas may be performed if safe, followed by neutralization using liquid sprays (e.g., calcium hydroxide). Ongoing monitoring ensures residual hazards are minimized.",
        "Storage tank protection involves safeguarding against fire, leaks, or other hazards. Key actions include applying liquid sprays (e.g., water) to cool and shield tanks, monitoring for damage or leaks, and performing repairs as needed. Timely interventions prevent escalation and maintain storage integrity.",
        "Pipeline protection focuses on preventing or mitigating damage, especially when carrying hazardous materials. Tasks include inspecting pipelines for leaks or weaknesses, applying sprays (liquid, solid, or gas) to suppress fires or cool the pipe, operating valves to control flow, and repairing damages. Monitoring confirms the effectiveness of interventions and prevents future incidents.",
    ]
    test_query = "Here is a high temp liquid fire"

    if "AdvancedRetriever" in globals() and HAS_ADVANCED_RAG:
        retriever = AdvancedRetriever()
        retriever.build_index(test_texts)
        print("[Test] AdvancedRetriever is_ready:", retriever.is_ready())
        indices, scores = retriever.search(test_query, top_k=3)
        print("[Test] AdvancedRetriever search indices:", indices)
        print("[Test] AdvancedRetriever search scores:", scores)
        for idx in indices:
            print("[Test] Result:", test_texts[idx])
    elif "SklearnRetriever" in globals() and HAS_SKLEARN:
        retriever = SklearnRetriever()
        retriever.build_index(test_texts)
        print("[Test] SklearnRetriever is_ready:", retriever.is_ready())
        indices, scores = retriever.search(test_query, top_k=3)
        print("[Test] SklearnRetriever search indices:", indices)
        print("[Test] SklearnRetriever search scores:", scores)
        for idx in indices:
            print("[Test] Result:", test_texts[idx])
    else:
        print(
            "[Test] 没有可用的检索器或依赖库未安装。请安装 sentence-transformers/faiss 或 scikit-learn。"
        )
