"""Project scaffolder — generate full project trees from descriptions.
DNA: Astra (code arena) + Cursor (multi-file).
"""

from pathlib import Path


PROJECT_TEMPLATES = {
    "python": {
        "files": {
            "main.py": '"""Main entry point."""\n\ndef main():\n    print("Hello from {{name}}!")\n\nif __name__ == "__main__":\n    main()\n',
            "requirements.txt": "# Project dependencies\n",
            "README.md": "# {{name}}\n\n{{description}}\n",
            ".gitignore": "__pycache__/\n*.pyc\n.env\nvenv/\n",
        }
    },
    "fastapi": {
        "files": {
            "main.py": '"""FastAPI application."""\nfrom fastapi import FastAPI\n\napp = FastAPI(title="{{name}}")\n\n@app.get("/")\nasync def root():\n    return {"message": "Hello from {{name}}"}\n',
            "requirements.txt": "fastapi\nuvicorn\n",
            "README.md": "# {{name}} — FastAPI Application\n\n{{description}}\n\n## Run\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.env\nvenv/\n",
        }
    },
    "react": {
        "files": {
            "package.json": '{\n  "name": "{{name}}",\n  "private": true,\n  "scripts": {\n    "dev": "vite",\n    "build": "vite build"\n  }\n}\n',
            "src/App.jsx": 'export default function App() {\n  return <div>{{description}}</div>;\n}\n',
            "src/main.jsx": 'import React from "react";\nimport ReactDOM from "react-dom/client";\nimport App from "./App";\n\nReactDOM.createRoot(document.getElementById("root")).render(<App />);\n',
            "index.html": '<!DOCTYPE html>\n<html>\n<head><title>{{name}}</title></head>\n<body><div id="root"></div></body>\n</html>\n',
            "README.md": "# {{name}} — React App\n\n{{description}}\n\n## Run\n```bash\nnpm install\nnpm run dev\n```\n",
        }
    },
}


def scaffold_project(template: str, name: str, description: str = "", 
                     output_dir: str = ".") -> str:
    """Generate a project from a template."""
    template = template.lower()
    if template not in PROJECT_TEMPLATES:
        available = ", ".join(PROJECT_TEMPLATES.keys())
        return f"Unknown template: {template}. Available: {available}"

    tpl = PROJECT_TEMPLATES[template]
    base = Path(output_dir).expanduser().resolve() / name

    files_created = []
    for filepath, content in tpl["files"].items():
        full_path = base / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = content.replace("{{name}}", name).replace("{{description}}", description)
        full_path.write_text(rendered)
        files_created.append(str(full_path.relative_to(base)))

    return f"""Project '{name}' created ({template} template)
Location: {base}
Files: {len(files_created)}
{chr(10).join(f'  {f}' for f in files_created)}"""