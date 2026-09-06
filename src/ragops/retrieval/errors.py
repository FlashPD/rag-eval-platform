"""Expected retrieval failures mapped to API responses."""


class RetrievalError(Exception):
    """Base class for typed retrieval failures."""


class DatasetNotIngestedError(RetrievalError):
    pass


class CompatibleIndexNotFoundError(RetrievalError):
    pass


class RetrievalLimitError(RetrievalError):
    pass


class ArtifactNotFoundError(RetrievalError):
    pass
