A11 KB Data Handoff
===================

Required runtime files:
  kb_records.pkl
  kb_index.npz

Optional diagnostic files:
  kb_fts.sqlite
  kb_fts_manifest.json
  build_meta.json
  _calib.json
  _probe.json

Required environment:
  A11_KB_REC=1
  A11_KB_DIR=<this directory>
  A11_RAG_KB=1

The KB index is lazy-loaded. It is not loaded by /health or ordinary text-only
interviews. It is used by /finish, learning-resource recommendation, and the
interview-time KB evidence channel when enabled.

This package does not contain API keys.
