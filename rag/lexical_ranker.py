"""In-memory BM25 over verified chunks; no new models or index writes.

Korean character n-grams tolerate spacing and particles without a tokenizer
dependency. Document and title fields can be ranked separately.
BM25: https://www.sqlite.org/fts5.html#the_bm25_function
"""
import math
import re
from collections import Counter


def terms(text):
    text = re.sub(r"description:|check_points:|actions:", " ", text.casefold())
    words = re.findall(r"[가-힣]+|[a-z]+|\d+(?:\.\d+)?", text)
    output = []
    for word in words:
        if re.fullmatch(r"[가-힣]+", word):
            output.extend(word[i:i+n] for n in (2, 3) for i in range(len(word)-n+1))
        else:
            output.append(word)
    # Cross-word Korean grams cover '부족 전압' / '부족전압'.
    compact = re.sub(r"\s+", "", text)
    for word in re.findall(r"[가-힣]+", compact):
        output.extend(word[i:i+3] for i in range(len(word)-2))
    return output


class BM25:
    def __init__(self, documents):
        self.documents = documents
        self.counts = []
        frequency = Counter()
        for document in documents:
            counts = Counter(terms(document))
            self.counts.append(counts)
            frequency.update(counts.keys())
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths)/max(1, len(documents)) or 1
        self.idf = {t: math.log(1+(len(documents)-f+.5)/(f+.5)) for t, f in frequency.items()}

    def scores(self, question):
        query = set(terms(question))
        result = []
        for counts, length in zip(self.counts, self.lengths):
            normalization = 1.2*(.25+.75*length/self.average)
            result.append(sum(self.idf[t]*counts[t]*2.2/(counts[t]+normalization)
                              for t in query & counts.keys()))
        return result
