class DocumentTooLargeError(Exception):
    def __init__(self, max_mb: int) -> None:
        self.max_mb = max_mb
        super().__init__(f"Document exceeds maximum size of {max_mb} MB")


class DocumentTypeNotSupportedError(Exception):
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Content type '{content_type}' is not supported")
