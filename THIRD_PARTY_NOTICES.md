# Third-party sources

## ENACT

- Source: <https://github.com/mll-lab-nu/ENACT>
- Imported revision: `87e323a985418f7dcb09e9f62d065a9d010ce98b`
- License: MIT; the original notice is retained in [ENACT/LICENSE](ENACT/LICENSE).
- The `ENACT/` subtree contains upstream code and local USIM adaptations. Upstream Git history is retained as a parent history of the workspace import.

## USIM

- Source: <https://huggingface.co/datasets/Vincent2025hello/usim>
- Pinned revision: `88c3612bf99d10652f19ec531052a38c04f0202e`
- License declared in the upstream dataset card: [Apache-2.0](LICENSES/Apache-2.0.txt). The original card is retained in [usim/README.md](usim/README.md).
- Original videos and Parquet are downloaded separately. The small benchmark contains extracted frames and annotations derived from this snapshot; retain the source revision and attribution when redistributing them.

## BEHAVIOR-1K

- Source: <https://github.com/StanfordVL/BEHAVIOR-1K>
- Submodule revision: `d19aec29e24dae41f81756326ee0dbeac742158a`
- The repository contains a Git submodule reference rather than a bundled copy. Consult the upstream repository for its terms before downloading or using it.

## Paper materials

`ENACT/docs/evidence/` includes source-grounded reading notes, extracted text and selected figures from the ENACT paper (`arXiv:2511.20937v1`). These retain their original authorship and publication terms; the ENACT software MIT license does not relicense the paper or the USIM dataset.
