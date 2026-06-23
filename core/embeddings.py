import math
from collections import Counter
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BaseEmbedder(ABC):
    @abstractmethod
    def fit(self, documents: list[str]):
        """Fit the vectorizer if required by the embedding technique (e.g. TF-IDF)."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a query text into a vector of floats."""
        pass

    @abstractmethod
    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        """Embed a list of document strings into a list of vector floats."""
        pass

    @property
    @abstractmethod
    def vocabulary(self) -> dict:
        """Expose a vocabulary mapping or dummy dimension representation to support compatibility checks."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Expose the embedder model/vocabulary state version string."""
        pass


class LocalTFIDFEmbedder(BaseEmbedder):
    def __init__(self, vocabulary: dict = None, idf: dict = None, doc_count: int = 0, model_path: str = "tfidf_model.json"):
        self._vocabulary = vocabulary or {}
        self.idf = idf or {}
        self.doc_count = doc_count
        self.model_path = model_path
        
        # Auto-load existing persisted model on startup
        if not self._vocabulary and self.model_path:
            self.load()

    def save(self, filepath: str = None):
        path = filepath or self.model_path
        if not path:
            return
        import json
        try:
            data = {
                "vocabulary": self._vocabulary,
                "idf": self.idf,
                "doc_count": self.doc_count
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved TF-IDF model to {path}")
        except Exception as e:
            logger.error(f"Failed to save TF-IDF model to {path}: {e}")

    def load(self, filepath: str = None):
        path = filepath or self.model_path
        if not path or not os.path.exists(path):
            return
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._vocabulary = data.get("vocabulary", {})
            self.idf = data.get("idf", {})
            self.doc_count = data.get("doc_count", 0)
            logger.info(f"Loaded TF-IDF model from {path}. Vocab size: {len(self._vocabulary)}")
        except Exception as e:
            logger.error(f"Failed to load TF-IDF model from {path}: {e}")

    def fit(self, documents: list[str]):
        """Fit the TF-IDF vectorizer vocabulary and compute IDF values on a list of document strings."""
        if not documents:
            logger.warning("No documents supplied to fit. TF-IDF vectorizer is empty.")
            return

        token_docs = [self._tokenize(d) for d in documents]
        self.doc_count = len(token_docs)
        
        # Count document frequency for each unique token
        df = Counter()
        for doc in token_docs:
            unique_tokens = set(doc)
            df.update(unique_tokens)

        # Build vocabulary indices
        vocab_list = sorted(list(df.keys()))
        self._vocabulary = {token: i for i, token in enumerate(vocab_list)}
        
        # Calculate Inverse Document Frequency with smoothing
        self.idf = {}
        for token, count in df.items():
            self.idf[token] = math.log((1 + self.doc_count) / (1 + count)) + 1
            
        logger.info(f"Fitted TF-IDF embedder. Vocab size: {len(self._vocabulary)} tokens on {self.doc_count} documents.")
        self.save()


    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase words and character 3-grams for typo-robust keyword matching."""
        text = text.lower()
        # Clean words
        words = []
        for w in text.split():
            clean_w = w.strip(".,!?;:()[]{}'\"-@#_*+=")
            if clean_w:
                words.append(clean_w)
        
        # Character 3-grams (typo-robustness feature)
        grams = []
        for word in words:
            if len(word) >= 3:
                for i in range(len(word) - 2):
                    grams.append(word[i:i+3])
            else:
                grams.append(word)
                
        return words + grams

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Returns a vector of floats."""
        return self.embed_documents([text])[0]

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        """Embed multiple document strings. Returns list of float lists."""
        vocab_size = len(self._vocabulary)
        if vocab_size == 0:
            return [[0.0] for _ in documents]

        vectors = []
        for doc in documents:
            tokens = self._tokenize(doc)
            tf = Counter(tokens)
            vector = [0.0] * vocab_size
            
            for token, count in tf.items():
                if token in self._vocabulary:
                    idx = self._vocabulary[token]
                    tf_val = count / len(tokens) if tokens else 0.0
                    idf_val = self.idf.get(token, 1.0)
                    vector[idx] = tf_val * idf_val
            
            # L2 Normalize the vector to allow exact Cosine Similarity using Inner Product
            norm = math.sqrt(sum(val**2 for val in vector))
            if norm > 0:
                vector = [val / norm for val in vector]
                
            vectors.append(vector)
            
        return vectors

    @property
    def vocabulary(self) -> dict:
        return self._vocabulary

    @property
    def version(self) -> str:
        return f"tfidf_{len(self._vocabulary)}"


class TFIDFEmbedder(LocalTFIDFEmbedder):
    pass


class BGEEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", model_path: str = "tfidf_model.json"):
        self.model_name = model_name
        self.dimension = 384
        self.fallback = None
        self._vocabulary = {str(i): i for i in range(self.dimension)}
        
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer model: {model_name}")
            self.model = SentenceTransformer(model_name)
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer model {model_name} ({e}). Falling back to LocalTFIDFEmbedder.")
            self.fallback = LocalTFIDFEmbedder(model_path=model_path)

    def fit(self, documents: list[str]):
        if self.fallback:
            self.fallback.fit(documents)
            self._vocabulary = self.fallback.vocabulary
        else:
            logger.info("BGEEmbedder does not require vocabulary fitting.")

    def embed_query(self, text: str) -> list[float]:
        if self.fallback:
            return self.fallback.embed_query(text)
        try:
            instruction = "Represent this sentence for searching relevant passages: "
            emb = self.model.encode(instruction + text, normalize_embeddings=True)
            return emb.tolist()
        except Exception as e:
            logger.error(f"BGE query embedding failed: {e}. Falling back to zero vector.")
            return [0.0] * self.dimension

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        if self.fallback:
            return self.fallback.embed_documents(documents)
        try:
            embs = self.model.encode(documents, normalize_embeddings=True)
            return embs.tolist()
        except Exception as e:
            logger.error(f"BGE documents embedding failed: {e}. Falling back to zero vectors.")
            return [[0.0] * self.dimension for _ in documents]

    @property
    def vocabulary(self) -> dict:
        if self.fallback:
            return self.fallback.vocabulary
        return self._vocabulary

    @property
    def version(self) -> str:
        if self.fallback:
            return self.fallback.version
        return f"bge_{self.model_name}"


class E5Embedder(BaseEmbedder):
    def __init__(self, model_name: str = "intfloat/e5-small-v2", model_path: str = "tfidf_model.json"):
        self.model_name = model_name
        self.dimension = 384
        self.fallback = None
        self._vocabulary = {str(i): i for i in range(self.dimension)}
        
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer model: {model_name}")
            self.model = SentenceTransformer(model_name)
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer model {model_name} ({e}). Falling back to LocalTFIDFEmbedder.")
            self.fallback = LocalTFIDFEmbedder(model_path=model_path)

    def fit(self, documents: list[str]):
        if self.fallback:
            self.fallback.fit(documents)
            self._vocabulary = self.fallback.vocabulary
        else:
            logger.info("E5Embedder does not require vocabulary fitting.")

    def embed_query(self, text: str) -> list[float]:
        if self.fallback:
            return self.fallback.embed_query(text)
        try:
            emb = self.model.encode("query: " + text, normalize_embeddings=True)
            return emb.tolist()
        except Exception as e:
            logger.error(f"E5 query embedding failed: {e}. Falling back to zero vector.")
            return [0.0] * self.dimension

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        if self.fallback:
            return self.fallback.embed_documents(documents)
        try:
            prefixed = ["passage: " + doc for doc in documents]
            embs = self.model.encode(prefixed, normalize_embeddings=True)
            return embs.tolist()
        except Exception as e:
            logger.error(f"E5 documents embedding failed: {e}. Falling back to zero vectors.")
            return [[0.0] * self.dimension for _ in documents]

    @property
    def vocabulary(self) -> dict:
        if self.fallback:
            return self.fallback.vocabulary
        return self._vocabulary

    @property
    def version(self) -> str:
        if self.fallback:
            return self.fallback.version
        return f"e5_{self.model_name}"


class NomicEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "nomic-embed-text-v1", model_path: str = "tfidf_model.json"):
        self.model_name = model_name
        self.dimension = 768
        self.fallback = None
        self._vocabulary = {str(i): i for i in range(self.dimension)}
        self.api_key = os.getenv("NOMIC_API_KEY")
        
        if not self.api_key:
            logger.warning("NOMIC_API_KEY environment variable not set. Falling back to LocalTFIDFEmbedder.")
            self.fallback = LocalTFIDFEmbedder(model_path=model_path)

    def fit(self, documents: list[str]):
        if self.fallback:
            self.fallback.fit(documents)
            self._vocabulary = self.fallback.vocabulary
        else:
            logger.info("NomicEmbedder does not require vocabulary fitting.")

    def embed_query(self, text: str) -> list[float]:
        if self.fallback:
            return self.fallback.embed_query(text)
        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.model_name,
                "texts": [text],
                "task_type": "search_query"
            }
            res = requests.post("https://api-atlas.nomic.ai/v1/embedding/text", headers=headers, json=data, timeout=10)
            res.raise_for_status()
            embeddings = res.json().get("embeddings")
            if embeddings:
                return embeddings[0]
            else:
                logger.error("Nomic API returned empty embeddings.")
                return [0.0] * self.dimension
        except Exception as e:
            logger.error(f"Nomic query embedding failed: {e}. Falling back to zero vector.")
            return [0.0] * self.dimension

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        if self.fallback:
            return self.fallback.embed_documents(documents)
        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.model_name,
                "texts": documents,
                "task_type": "search_document"
            }
            res = requests.post("https://api-atlas.nomic.ai/v1/embedding/text", headers=headers, json=data, timeout=15)
            res.raise_for_status()
            embeddings = res.json().get("embeddings")
            if embeddings:
                return embeddings
            else:
                logger.error("Nomic API returned empty embeddings.")
                return [[0.0] * self.dimension for _ in documents]
        except Exception as e:
            logger.error(f"Nomic documents embedding failed: {e}. Falling back to zero vectors.")
            return [[0.0] * self.dimension for _ in documents]

    @property
    def vocabulary(self) -> dict:
        if self.fallback:
            return self.fallback.vocabulary
        return self._vocabulary

    @property
    def version(self) -> str:
        if self.fallback:
            return self.fallback.version
        return f"nomic_{self.model_name}"


def get_embedder(model_path: str = "tfidf_model.json") -> BaseEmbedder:
    embedder_type = os.getenv("EMBEDDER_TYPE", "tfidf").lower()
    if embedder_type == "bge":
        return BGEEmbedder(model_path=model_path)
    elif embedder_type == "nomic":
        return NomicEmbedder(model_path=model_path)
    elif embedder_type == "e5":
        return E5Embedder(model_path=model_path)
    else:
        return TFIDFEmbedder(model_path=model_path)

