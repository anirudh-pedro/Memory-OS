
import os


class Embedder:
    _model = None

    def __init__(self, model_name: str | None = None):
        if model_name:
            self.model_name = model_name
        else:
            self.model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    @property
    def model(self):
        if Embedder._model is None:
            # Load SentenceTransformer model
            from sentence_transformers import SentenceTransformer
            try:
                Embedder._model = SentenceTransformer(self.model_name)
            except Exception as e:
                # If network fails or times out, try loading from local cache only
                try:
                    Embedder._model = SentenceTransformer(self.model_name, local_files_only=True)
                except Exception:
                    raise e
        return Embedder._model

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
