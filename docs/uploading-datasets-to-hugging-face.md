# Uploading datasets to Hugging Face

Publish one Hugging Face dataset repository for each standalone dataset or database
snapshot you want people to download. Use one named **configuration** (also called
a subset) for each collection. Within a configuration, a **split** is a named
partition of the records, such as `train` or `test`. A split can span multiple
files. For a complete export with no partitions, use a single split such as `full`.

## Prepare the files and dataset card

Put only the files you intend to publish in a staging folder. This example uses
`forum-data/` with `README.md`, `users.jsonl` and `posts.jsonl`. For a standalone
collection, use the same layout with just one data file and configuration.

Put the following YAML at the top of `README.md`. Paths are relative to the
repository root. Choose configuration names that match the destination
collections when using BONDI's repository loader.

```yaml
---
configs:
  - config_name: users
    data_files:
      - split: full
        path: users.jsonl
  - config_name: posts
    data_files:
      - split: full
        path: posts.jsonl
---
```

If posts have separate training and test files, give the `posts` configuration
two `data_files` entries with the corresponding split names and paths. Keep any
other collections in their own configurations. See
[Hugging Face's manual configuration guide](https://huggingface.co/docs/hub/datasets-manual-configuration)
for examples with multiple files per split.

Below the YAML, describe where the data came from, how the files were generated,
and which source tables were joined or embedded. Include the source revision or
snapshot date where known, attribution and licence information, and any types
that need special handling, such as MongoDB Extended JSON dates.

## Upload with the Hugging Face CLI

Install the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli).
Run `hf auth login` with a token that can write to the destination namespace,
then check the account with `hf auth whoami`.

From the directory containing `forum-data/`, run the following. Replace
`your-namespace` with your Hugging Face username or organisation. The
`--repo-type dataset` flag selects a dataset repository, and `--private` makes
a newly created repository private while you verify the upload.

```sh
hf upload your-namespace/forum-data ./forum-data --repo-type dataset --private
```

With uv installed, you can run the same commands in an isolated environment by
prefixing them with `uvx --from huggingface-hub`. For large exports, check the
[Hub storage limits](https://huggingface.co/docs/hub/storage-limits) and
[upload guidance](https://huggingface.co/docs/huggingface_hub/main/guides/upload).

## Verify the upload

1. Open the dataset's **Files and versions** tab and confirm that the card and
   all the data files are present.
2. Check that Hugging Face Datasets discovers the intended configurations and
   splits. You can use `get_dataset_config_names(repo_id)` and
   `get_dataset_split_names(repo_id, config_name)` from the `datasets` package.
3. Try importing one configuration into a test collection. Use
   `load_hf_dataset` to choose the configuration and the exact destination.
   To load every configuration into a same-named MongoDB collection in one
   database, use the repository loader.

```sh
bondi dataset load-hf-repository your-namespace/forum-data \
  --deployment notebook-datasets --database forum
```

The repository loader combines all splits of each configuration by default.
When you select a split for the entire repository, it must exist in every
configuration. Pin a commit with `--revision` for reproducible imports.

When a split uses only Hub JSONL files (`.jsonl` or `.jsonl.gz`), BONDI
streams the original records and preserves missing fields and explicit nulls.
Use `--json-mode extended` for MongoDB Extended JSON exports. Other formats
use Hugging Face readers, which can normalise records to a shared schema.
See the [dataset loading guide](datasets.md) for details.
