# AI-First Pipeline Documentation

This directory contains architecture diagrams and documentation for the AI-First Pipeline project.

## Architecture Diagrams

### Overview
- **[architecture-overview.mmd](architecture-overview.mmd)** - High-level system architecture showing major components and their relationships

### Detailed Views
- **[architecture-infrastructure.mmd](architecture-infrastructure.mmd)** - Infrastructure details: VM, K3s cluster, persistent storage, services, and secrets
- **[architecture-jobs-runners.mmd](architecture-jobs-runners.mmd)** - Job execution: K8s Jobs, agent runners (SDK vs CLI), and skill configuration
- **[architecture-data-flow.mmd](architecture-data-flow.mmd)** - Data pipeline flow: from bug fetch through execution to dashboard visualization

### Sequence Diagrams
- **[pipeline-execution-flow.mmd](pipeline-execution-flow.mmd)** - Complete execution sequence showing interactions between all components

### Legacy
- **[architecture.mmd](architecture.mmd)** - Comprehensive single-diagram view (replaced by modular diagrams above)

## Viewing the Diagrams

These diagrams use Mermaid syntax and render automatically on GitHub. To view them:

1. **On GitHub**: Click any `.mmd` file to see the rendered diagram
2. **Locally**: Use a Mermaid preview extension for your editor, or paste the content into [Mermaid Live Editor](https://mermaid.live/)

## Diagram Conventions

- **Colors**:
  - Blue: Storage/PVCs
  - Orange: Services/Infrastructure
  - Purple: Jobs/Execution
  - Green: External Services
  - Pink: Runners/Agents
  - Yellow: Skills/Configuration
  - Red: Security/Secrets

- **Layout**: All diagrams use vertical (top-to-bottom) orientation for better GitHub rendering
