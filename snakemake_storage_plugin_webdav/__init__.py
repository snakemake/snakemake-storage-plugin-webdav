from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional, List
from urllib.parse import urlparse

from webdav3.client import Client

from snakemake_interface_storage_plugins.settings import StorageProviderSettingsBase
from snakemake_interface_storage_plugins.storage_provider import (  # noqa: F401
    StorageProviderBase,
    StorageQueryValidationResult,
    ExampleQuery,
    Operation,
    QueryType,
)
from snakemake_interface_storage_plugins.storage_object import (
    StorageObjectRead,
    StorageObjectWrite,
    StorageObjectGlob,
    retry_decorator,
)
from snakemake_interface_storage_plugins.io import IOCacheStorageInterface, get_constant_prefix


# Optional:
# Define settings for your storage plugin (e.g. host url, credentials).
# They will occur in the Snakemake CLI as --storage-<storage-plugin-name>-<param-name>
# Make sure that all defined fields are 'Optional' and specify a default value
# of None or anything else that makes sense in your case.
# Note that we allow storage plugin settings to be tagged by the user. That means,
# that each of them can be specified multiple times (an implicit nargs=+), and
# the user can add a tag in front of each value (e.g. tagname1:value1 tagname2:value2).
# This way, a storage plugin can be used multiple times within a workflow with different
# settings.
@dataclass
class StorageProviderSettings(StorageProviderSettingsBase):
    username: Optional[str] = field(
        default=None,
        metadata={
            "help": "Webdav username",
            "env_var": True,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )
    password: Optional[str] = field(
        default=None,
        metadata={
            "help": "Webdav username",
            "env_var": True,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )
    host: Optional[str] = field(
        default=None,
        metadata={
            "help": "Webdav hostname",
            "env_var": False,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )
    port: int = field(
        default=443,
        metadata={
            "help": "Webdav port",
            "env_var": False,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )
    protocol: str = field(
        default="https",
        metadata={
            "help": "Webdav protocol",
            "choices": ["http", "https"],
            "env_var": False,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )
    timeout: int = field(
        default=30,
        metadata={
            "help": "Webdav timeout",
            "env_var": False,
            # Optionally specify that setting is required when the executor is in use.
            "required": True,
        },
    )


# Required:
# Implementation of your storage provider
# This class can be empty as the one below.
# You can however use it to store global information or maintain e.g. a connection
# pool.
class StorageProvider(StorageProviderBase):
    # For compatibility with future changes, you should not overwrite the __init__
    # method. Instead, use __post_init__ to set additional attributes and initialize
    # futher stuff.

    def __post_init__(self):
        # This is optional and can be removed if not needed.
        # Alternatively, you can e.g. prepare a connection to your storage backend here.
        # and set additional attributes.
        port = f":{self.settings.port}" if self.settings.port != 443 else ""
        self.client = Client(
            {
                "webdav_hostname": f"{self.settings.protocol}://{self.settings.host}{port}",
                "webdav_login": self.settings.username,
                "webdav_password": self.settings.password,
                "webdav_timeout": self.settings.timeout,
            }
        )

    @classmethod
    def example_queries(cls) -> List[ExampleQuery]:
        """Return an example queries with description for this storage provider (at
        least one)."""
        return [
            ExampleQuery(
                query="dav://path/to/file.txt",
                description="A file on a webdav server",
                type=QueryType.ANY,
            )
        ]

    def rate_limiter_key(self, query: str, operation: Operation) -> Any:
        """Return a key for identifying a rate limiter given a query and an operation.

        This is used to identify a rate limiter for the query.
        E.g. for a storage provider like http that would be the host name.
        For s3 it might be just the endpoint URL.
        """
        return (self.settings.host, self.settings.port)

    def default_max_requests_per_second(self) -> float:
        """Return the default maximum number of requests per second for this storage
        provider."""
        return 10.0

    def use_rate_limiter(self) -> bool:
        """Return False if no rate limiting is needed for this provider."""
        return True

    @classmethod
    def is_valid_query(cls, query: str) -> StorageQueryValidationResult:
        """Return whether the given query is valid for this storage provider."""
        # Ensure that also queries containing wildcards (e.g. {sample}) are accepted
        # and considered valid. The wildcards will be resolved before the storage
        # object is actually used.
        if query.startswith("dav://"):
            return StorageQueryValidationResult(
                is_valid=True, query=query,
            )
        else:
            return StorageQueryValidationResult(is_valid=False, query=query, reason="Query has to start with dav://")


# Required:
# Implementation of storage object. If certain methods cannot be supported by your
# storage (e.g. because it is read-only see
# snakemake-storage-http for comparison), remove the corresponding base classes
# from the list of inherited items.
class StorageObject(StorageObjectRead, StorageObjectWrite, StorageObjectGlob):
    # For compatibility with future changes, you should not overwrite the __init__
    # method. Instead, use __post_init__ to set additional attributes and initialize
    # futher stuff.

    def __post_init__(self):
        # This is optional and can be removed if not needed.
        # Alternatively, you can e.g. prepare a connection to your storage backend here.
        # and set additional attributes.
        self.parsed = urlparse(self.query)
        self.path = f"{self.parsed.netloc}/{self.parsed.path}"

    async def inventory(self, cache: IOCacheStorageInterface):
        """From this file, try to find as much existence and modification date
        information as possible. Only retrieve that information that comes for free
        given the current object.
        """
        # This is optional and can be left as is

        # If this is implemented in a storage object, results have to be stored in
        # the given IOCache object, using self.cache_key() as key.
        # Optionally, this can take a custom local suffix, needed e.g. when you want
        # to cache more items than the current query: self.cache_key(local_suffix=...)
        # TODO implement
        pass

    def get_inventory_parent(self) -> Optional[str]:
        """Return the parent directory of this object."""
        # this is optional and can be left as is
        return None

    def local_suffix(self) -> str:
        """Return a unique suffix for the local path, determined from self.query."""
        return self.path

    def cleanup(self):
        """Perform local cleanup of any remainders of the storage object."""
        # self.local_path() should not be removed, as this is taken care of by
        # Snakemake.
        pass

    # Fallible methods should implement some retry logic.
    # The easiest way to do this (but not the only one) is to use the retry_decorator
    # provided by snakemake-interface-storage-plugins.
    @retry_decorator
    def exists(self) -> bool:
        # return True if the object exists
        self.provider.client.check(self.path)

    @retry_decorator
    def mtime(self) -> float:
        # return the modification time
        modified = self.provider.client.info(self.path)["modified"]
        return datetime.strptime(modified, "%a, %d %b %Y %H:%M:%S %Z")

    @retry_decorator
    def size(self) -> int:
        # return the size in bytes
        return int(self.provider.client.info(self.path)["size"])

    @retry_decorator
    def retrieve_object(self):
        # Ensure that the object is accessible locally under self.local_path()
        self.provider.client.download_sync(remote_path=self.path, local_path=self.local_path())

    # The following to methods are only required if the class inherits from
    # StorageObjectReadWrite.

    @retry_decorator
    def store_object(self):
        # Ensure that the object is stored at the location specified by
        # self.local_path().
        self.provider.client.upload_sync(remote_path=self.path, local_path=self.local_path())

    @retry_decorator
    def remove(self):
        # Remove the object from the storage.
        self.provider.client.clean(self.path)

    # The following to methods are only required if the class inherits from
    # StorageObjectGlob.

    @retry_decorator
    def list_candidate_matches(self) -> Iterable[str]:
        """Return a list of candidate matches in the storage for the query."""
        # This is used by glob_wildcards() to find matches for wildcards in the query.
        # The method has to return concretized queries without any remaining wildcards.
        # Use snakemake_executor_plugins.io.get_constant_prefix(self.query) to get the
        # prefix of the query before the first wildcard.
        prefix = get_constant_prefix(self.path, strip_incomplete_parts=True)
        if prefix:
            return [item.path for item in self.provider.client.list(prefix, recursive=True, get_info=True)]
