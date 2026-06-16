# Social Graph Runbook

This guide summarizes how to run the **Social Graph** pipeline and web dashboard. 

---

## 🌐 1. Start the Web Dashboard (Frontend & Backend)
The web dashboard serves both the REST API backend and the vanilla JS/CSS frontend interface. 

To start the server:
```bash
sg web
```
* **Default URL**: [http://localhost:8080](http://localhost:8080) (it will automatically open in your default browser).
* **Custom Port**: To run on a different port:
  ```bash
  sg web --port 8080 --no-open
  ```

---

## ⏱️ 2. Run in the Background (Continuous Scheduler)
To continuously check for new LinkedIn posts, extract comments, enrich data, and update your Obsidian vault automatically:

* **Start the Scheduler Daemon**:
  ```bash
  sg schedule start --interval-hours 6
  ```
  *(This will immediately trigger a run, then repeat every 6 hours).*
  
* **Check Status & PID**:
  ```bash
  sg schedule status
  ```
  
* **Stop the Scheduler**:
  ```bash
  sg schedule stop
  ```

---

## 🚀 3. Run the Pipeline Manually (Fully or Partially)
If you want to run the pipeline instantly in your current terminal:

### Full Manual Run
```bash
sg run
```
* **Automatic Live Fallback**: If the local `linkedin_saved_posts.json` export file is missing, the command will print a warning and automatically fall back to live web scraping via Playwright.
* **Force Live Scraper (Visible Browser)**: If you need to handle LinkedIn MFA/2FA, run:
  ```bash
  sg run --live --no-headless
  ```

### Resuming or Running Specific Stages
You can bypass stages or target a single step of the pipeline:
* **Resume from a specific stage** (e.g. if ingestion is done and you want to start at classification):
  ```bash
  sg run --from classify
  ```
* **Run a single stage only**:
  ```bash
  sg run --stage embed
  ```

---

## 🔧 4. Reference: CLI Command List
You can also invoke specific helper tools individually:

| Command | Description |
|---------|-------------|
| `sg status` | Show database stats and scheduler status |
| `sg ingest --live` | Scrape and ingest new LinkedIn saved posts |
| `sg scrape` | Scrape and ingest new posts with a visible browser window (for 2FA/login) |
| `sg comments` | Scrape post comments |
| `sg comment-enrich` | Fetch and summarize external links in comments |
| `sg enrich` | Fetch and summarize external links in post bodies |
| `sg classify` | Classify enriched posts into topics |
| `sg embed` | Generate local/GPU embeddings for posts |
| `sg subtopic` | Generate titles and subtopics for posts |
| `sg semantic-edges` | Build graph edges based on semantic similarity |
| `sg build-graph` | Detect communities and construct the knowledge graph |
| `sg vault-write` | Write/rebuild all notes in your Obsidian vault |
| `sg search "query"` | Search your database semantically via CLI |
| `sg similar "urn"` | Find semantically similar posts in your database |
