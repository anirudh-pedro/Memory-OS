import os
from sentence_transformers import SentenceTransformer

class Embedder:
    def __init__(self):
        self.model_name = "all-MiniLM-L6-v2"
        self._model = None

    @property
    def model(self):
        if self._model is None:
            # Load SentenceTransformer model
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def fit(self, documents=None):
        # SentenceTransformer all-MiniLM-L6-v2 is pre-trained, so this is a no-op
        pass

    def embed_documents(self, texts: list) -> list:
        if not texts:
            return []
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def embed_query(self, text: str) -> list:
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def dimension(self) -> int:
        return 384

    def version(self) -> str:
        return "all-MiniLM-L6-v2-384"
