"""What the saved neighbours of the running `text-hybrid` policy mean, without its mathematics.

The web process only reads precomputed `GameNeighbors`; it needs the policy identity and the
shape of each stored reason, not NumPy or the ranking itself. `similarity.text` re-exports these
names, so the ranking and the reader cannot disagree about them.
"""

POLICY_ID = "text-hybrid"
POLICY_VERSION = "3.0.0"
MAX_RESULTS = 5
MAX_SHARED_TERMS = 3

BASIS_DESCRIPTION = "description"
BASIS_TITLE = "title"
