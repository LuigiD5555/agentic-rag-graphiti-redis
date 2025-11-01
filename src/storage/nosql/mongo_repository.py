class MongoRepository:
    def __init__(self, url: str, db: str):
        self.url = url
        self.db = db
