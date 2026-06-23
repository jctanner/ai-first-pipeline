Here’s the distilled recommendation:

---

**Problem**

* Your architecture docs are optimized for humans, not agents
* Agents waste ~54% of calls on navigation (`ls`, `grep`)
* They read ~300 lines to extract ~50 useful lines
* 20% of runs fail before reading any content

---

**Core Solution**
Add a **lightweight, structured index layer** on top of existing markdown docs (no changes to generator).

---

**New Structure**

```
architecture-context/
  index/
    INDEX.yaml              # entrypoint (component registry)
    components/*.yaml       # per-component fact sheets
    graphs/*.yaml           # dependencies, CRDs, ports
  architecture/             # existing markdown (unchanged)
  overlays/                 # unchanged (pre-applied if possible)
```

---

**Key Pieces**

1. **INDEX.yaml**

   * Maps component names + aliases → file paths
   * Eliminates all `ls | grep` discovery

2. **Component YAMLs**

   * ~40–80 lines each
   * Contain only:

     * CRDs
     * ports
     * dependencies
     * integrations
     * purpose
   * Replace reading full 300-line docs

3. **Graph Files**

   * Explicit cross-component relationships
   * Examples:

     * dependencies.yaml
     * crd-index.yaml
     * ports-index.yaml

---

**Agent Workflow (After)**

1. Read `INDEX.yaml`
2. Jump directly to relevant components
3. Read 1–3 small YAML files
4. Only read full markdown if needed

---

**Expected Impact**

* −50–70% tool calls (no navigation)
* −60–80% tokens (no over-reading)
* ~0% discovery failures
* Faster + more reliable reasoning

---

**Implementation**

* Add a **post-processing step**:

  * Parse markdown → extract structured facts → generate YAML index
* Do NOT modify existing doc generator

---

**Key Insight**
Agents need:

* direct entrypoint
* compressed facts
* explicit relationships

Not:

* directory exploration
* long prose
* implicit structure

---

**Bottom Line**
Keep your docs, but add a **thin, agent-first index layer** that turns them into a fast, queryable system.

