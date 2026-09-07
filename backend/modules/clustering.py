"""Group similar free-text responses so Claude can name themes over groups.

Sending a thousand raw responses to an LLM and asking for themes produces a
plausible-sounding summary that nobody can audit. Clustering first means each
theme is a real, countable set of responses you can open and read.
"""

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

# Beyond this many groups a themes dashboard stops being readable.
MAX_CLUSTERS = 12
MIN_CLUSTERS = 2
# Responses per cluster we aim for when choosing the search range for k.
TARGET_CLUSTER_SIZE = 12


@dataclass
class Cluster:
    id: int
    row_indices: list[int]
    exemplars: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.row_indices)


def _vectorizer(n_docs: int) -> TfidfVectorizer:
    # min_df=2 drops words appearing once, which is most of the vocabulary on a
    # small survey -- so only apply it when there are enough documents to spare.
    return TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2 if n_docs >= 50 else 1,
        max_df=0.85 if n_docs >= 20 else 1.0,
        sublinear_tf=True,
        strip_accents="unicode",
    )


def _choose_k(matrix, n_docs: int) -> int:
    """Pick a cluster count by silhouette score over a sensible range."""
    upper = min(MAX_CLUSTERS, max(MIN_CLUSTERS, n_docs // TARGET_CLUSTER_SIZE))
    if upper < MIN_CLUSTERS:
        return MIN_CLUSTERS

    best_k, best_score = MIN_CLUSTERS, -1.0
    for k in range(MIN_CLUSTERS, upper + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(matrix, labels, metric="cosine")
        if score > best_score:
            best_k, best_score = k, score
    return best_k


def cluster_responses(texts: list[str], row_indices: list[int]) -> list[Cluster]:
    """Cluster responses and return them with exemplars and keywords.

    Callers must check `config.MIN_RESPONSES_FOR_CLUSTERING` first -- below that
    threshold the responses should go to Claude un-clustered, because TF-IDF
    over a few dozen short answers has too little signal to split on.
    """
    if len(texts) != len(row_indices):
        raise ValueError("texts and row_indices must be the same length")
    if not texts:
        return []

    vectorizer = _vectorizer(len(texts))
    matrix = vectorizer.fit_transform(texts)

    # An empty vocabulary means every response was stop words or punctuation.
    if matrix.shape[1] == 0:
        return [Cluster(id=0, row_indices=list(row_indices), exemplars=texts[:5])]

    k = _choose_k(matrix, len(texts))
    model = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = model.fit_predict(matrix)

    terms = np.array(vectorizer.get_feature_names_out())
    clusters: list[Cluster] = []

    for label in sorted(set(labels)):
        member_positions = [i for i, lab in enumerate(labels) if lab == label]
        if not member_positions:
            continue

        centroid = model.cluster_centers_[label]
        # Rank members by cosine similarity to their centroid; the closest ones
        # are the most representative quotes to show a human.
        member_matrix = matrix[member_positions]
        similarities = member_matrix @ centroid
        similarities = np.asarray(similarities).ravel()
        ranked = [member_positions[i] for i in np.argsort(similarities)[::-1]]

        top_term_idx = [i for i in np.argsort(centroid)[::-1][:6] if centroid[i] > 0]
        keywords = [str(t) for t in terms[top_term_idx]]

        clusters.append(
            Cluster(
                id=int(label),
                row_indices=[row_indices[i] for i in member_positions],
                exemplars=[texts[i] for i in ranked[:5]],
                keywords=keywords,
            )
        )

    clusters.sort(key=lambda c: c.size, reverse=True)
    return clusters
