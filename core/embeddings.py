import math
from collections import Counter
import logging

logger = logging.getLogger(__name__)

class LocalTFIDFEmbedder:
    def __init__(self, vocabulary: dict = None, idf: dict = None, doc_count: int = 0):
        self.vocabulary = vocabulary or {}
        self.idf = idf or {}
        self.doc_count = doc_count

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
        self.vocabulary = {token: i for i, token in enumerate(vocab_list)}
        
        # Calculate Inverse Document Frequency with smoothing
        self.idf = {}
        for token, count in df.items():
            self.idf[token] = math.log((1 + self.doc_count) / (1 + count)) + 1
            
        logger.info(f"Fitted TF-IDF embedder. Vocab size: {len(self.vocabulary)} tokens on {self.doc_count} documents.")

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
        vocab_size = len(self.vocabulary)
        if vocab_size == 0:
            return [[0.0] for _ in documents]

        vectors = []
        for doc in documents:
            tokens = self._tokenize(doc)
            tf = Counter(tokens)
            vector = [0.0] * vocab_size
            
            for token, count in tf.items():
                if token in self.vocabulary:
                    idx = self.vocabulary[token]
                    tf_val = count / len(tokens) if tokens else 0.0
                    idf_val = self.idf.get(token, 1.0)
                    vector[idx] = tf_val * idf_val
            
            # L2 Normalize the vector to allow exact Cosine Similarity using Inner Product
            norm = math.sqrt(sum(val**2 for val in vector))
            if norm > 0:
                vector = [val / norm for val in vector]
                
            vectors.append(vector)
            
        return vectors
