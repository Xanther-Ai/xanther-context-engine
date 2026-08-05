"""
Export Service for XCE Dashboard
Exports nodes in various formats (JSON, CSV, DOT)
"""

import json
import csv
from io import StringIO
from typing import List
from neo4j import AsyncGraphDatabase


class ExportService:
    """Exports data in various formats"""
    
    def __init__(self, driver: AsyncGraphDatabase.driver):
        self.driver = driver
    
    async def export_json(self, repo_id: str, node_ids: List[str]) -> str:
        """Export nodes to JSON format"""
        async with self.driver.session() as session:
            placeholders = ", ".join([f"$id{i}" for i in range(len(node_ids))])
            params = {f"id{i}": nid for i, nid in enumerate(node_ids)}
            params["repo_id"] = repo_id
            
            query = f"""
                MATCH (n:ASTNode {{repo_id: $repo_id}})
                WHERE n.id IN [{placeholders}]
                OPTIONAL MATCH (n)-[r]->(m:ASTNode {{repo_id: $repo_id}})
                RETURN n, collect({{source: n.id, target: m.id, relation: type(r)}}) as edges
            """
            
            result = await session.run(query, params)
            
            nodes = []
            edges = []
            async for record in result:
                n = record["n"]
                node_data = {
                    "id": n.get("id"),
                    "name": n.get("name"),
                    "kind": n.get("kind"),
                    "filepath": n.get("filepath"),
                    "start_line": n.get("start_line"),
                    "end_line": n.get("end_line"),
                    "docstring": n.get("docstring"),
                    "signature": n.get("signature"),
                    "source_text": n.get("source_text")
                }
                nodes.append(node_data)
                
                for edge in record["edges"]:
                    if edge["target"]:
                        edges.append(edge)
            
            return json.dumps({
                "nodes": nodes,
                "edges": edges,
                "metadata": {
                    "repo_id": repo_id,
                    "exported_at": self._get_timestamp()
                }
            }, indent=2)
    
    async def export_csv(self, repo_id: str, node_ids: List[str]) -> str:
        """Export nodes to CSV format"""
        async with self.driver.session() as session:
            placeholders = ", ".join([f"$id{i}" for i in range(len(node_ids))])
            params = {f"id{i}": nid for i, nid in enumerate(node_ids)}
            params["repo_id"] = repo_id
            
            query = f"""
                MATCH (n:ASTNode {{repo_id: $repo_id}})
                WHERE n.id IN [{placeholders}]
                RETURN n.id, n.name, n.kind, n.filepath, n.start_line, n.end_line, n.docstring
            """
            
            result = await session.run(query, params)
            
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "name", "kind", "filepath", "start_line", "end_line", "docstring"])
            
            async for record in result:
                writer.writerow([
                    record["n.id"],
                    record["n.name"],
                    record["n.kind"],
                    record["n.filepath"],
                    record["n.start_line"],
                    record["n.end_line"],
                    (record["n.docstring"] or "")[:100]
                ])
            
            return output.getvalue()
    
    async def export_dot(self, repo_id: str, node_ids: List[str]) -> str:
        """Export graph to DOT format for Graphviz"""
        async with self.driver.session() as session:
            placeholders = ", ".join([f"$id{i}" for i in range(len(node_ids))])
            params = {f"id{i}": nid for i, nid in enumerate(node_ids)}
            params["repo_id"] = repo_id
            
            # Get nodes
            query = f"""
                MATCH (n:ASTNode {{repo_id: $repo_id}})
                WHERE n.id IN [{placeholders}]
                RETURN n.id as id, n.name as name, n.kind as kind
            """
            
            result = await session.run(query, params)
            
            lines = ["digraph XCE {", "  rankdir=LR;", "  node [shape=box];"]
            
            # Color mapping by kind
            colors = {
                "class": "lightblue",
                "function": "lightgreen",
                "method": "lightgreen",
                "module": "lightyellow",
                "import": "lightgray"
            }
            
            async for record in result:
                color = colors.get(record["kind"], "white")
                safe_name = record["name"].replace('"', '\\"')
                lines.append(f'  "{record["id"]}" [label="{safe_name}", style=filled, fillcolor="{color}"];')
            
            # Get edges
            query = f"""
                MATCH (a:ASTNode {{repo_id: $repo_id}})-[r]->(b:ASTNode {{repo_id: $repo_id}})
                WHERE a.id IN [{placeholders}] AND b.id IN [{placeholders}]
                RETURN a.id as source, b.id as target, type(r) as relation
            """
            
            result = await session.run(query, params)
            
            async for record in result:
                lines.append(f'  "{record["source"]}" -> "{record["target"]}" [label="{record["relation"]}"];')
            
            lines.append("}")
            return "\n".join(lines)
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()