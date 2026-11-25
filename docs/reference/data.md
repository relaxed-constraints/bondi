# Dataset loading

Loaders accept [connection settings](connection.md) and share the same write path. Create and replace use batched inserts
bounded by `batch_size`. See [progress and failures](../datasets.md#progress-and-failures)
for partial failure behavior.

::: bondi.data.load_demo_data
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.load_file
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.load_documents
    options:
      show_root_heading: true
      heading_level: 2

Both Hugging Face loaders default to `streaming=False` and use Hugging Face's
disk caches. Pass `streaming=True` to read remotely instead. See
[caching and streaming](../datasets.md#hugging-face-caching-and-streaming)
for cache locations, CLI flags and storage tradeoffs.

::: bondi.data.load_hf_dataset
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.load_hf_repository
    options:
      show_root_heading: true
      heading_level: 2

AptMQL loaders read related BSON collections into named databases or scopes.
See [AptMQL datasets](../datasets.md#load-aptmql-databases) for source selection,
namespace mappings, and the available datasets. Dump indexes are not restored.

::: bondi.data.load_aptmql_dataset
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.load_aptmql_repository
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.LoadDataResult
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.LoadDataError
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.list_datasets
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.data.dataset_info
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.postgresql.PostgresCollectionRef
    options:
      show_root_heading: true
      heading_level: 2
