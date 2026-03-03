"""
Database router so PBM/claims models use the knowledge database
(data/knowledge.db) instead of default.
"""


class KnowledgeRouter:
    """Send models in the 'knowledge' app_label to the knowledge DB."""

    knowledge_models = {"pbmclaim"}

    def db_for_read(self, model, **hints):
        if model._meta.model_name.lower() in self.knowledge_models:
            return "knowledge"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.model_name.lower() in self.knowledge_models:
            return "knowledge"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Do not run migrations for our unmanaged model on knowledge (table exists).
        if db == "knowledge":
            return False
        return None
