// XCE Dashboard Type Definitions

export interface Repository {
  repo_id: string;
  name: string;
  path: string;
  status: 'pending' | 'indexing' | 'indexed' | 'error';
  node_count: number;
  edge_count: number;
  last_indexed: string | null;
  error_message: string | null;
}

export interface SearchResult {
  node_id: string;
  name: string;
  filepath: string;
  start_line: number;
  end_line: number;
  kind: string;
  score: number;
  snippet: string;
}

export interface GraphNode {
  id: string;
  name: string;
  kind: string;
  filepath: string;
  start_line: number;
  end_line: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface RepositoryStats {
  repo_id: string;
  total_nodes: number;
  nodes_by_kind: Record<string, number>;
  total_edges: number;
  edges_by_type: Record<string, number>;
  files_by_extension: Record<string, number>;
  total_lines: number;
  last_indexed: string | null;
}

export interface Settings {
  neo4j_uri: string;
  neo4j_user: string;
  embedding_model: string;
  embedding_dimensions: number;
  batch_size: number;
  server_port: number;
  auth_enabled: boolean;
}

export interface IndexingProgress {
  repo_id: string;
  total_files: number;
  processed_files: number;
  current_file: string | null;
  nodes_created: number;
  edges_created: number;
  percent: number;
  status: string;
}