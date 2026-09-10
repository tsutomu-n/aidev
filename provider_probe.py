"""Read installed provider schemas without starting servers or loading repo code."""
import json
import sys
from pathlib import Path


def main():
    provider, root_text = sys.argv[1:3]
    root = Path(root_text)
    if provider == "graphify":
        from graphify.detect import CODE_EXTENSIONS
        from graphify.manifest_ingest import PACKAGE_MANIFEST_NAMES
        print(json.dumps({"code_extensions": sorted(CODE_EXTENSIONS), "code_names": sorted(PACKAGE_MANIFEST_NAMES)}))
        return
    if provider == "crg":
        from code_review_graph.incremental import get_data_dir
        from code_review_graph.parser import EXTENSION_TO_LANGUAGE
        print(json.dumps({"data_dir": str(get_data_dir(root, create=False)), "code_extensions": sorted(EXTENSION_TO_LANGUAGE)}))
        return

    from ruamel.yaml import YAML
    from serena.config.serena_config import ProjectConfig, SerenaConfig
    from serena.constants import SERENA_CONFIG_TEMPLATE_FILE
    from solidlsp.ls_config import LanguageServerId

    yaml = YAML(typ="safe")
    languages = json.loads(sys.argv[3])
    project_path = root / ".serena/project.yml"
    if project_path.exists():
        # Pure parsing, unlike ProjectConfig.load which can migrate files.
        project = yaml.load(project_path.read_text())
        full, _ = ProjectConfig._load_yaml_dict(str(project_path))
        ProjectConfig._from_dict(full, local_override_keys=[])
    else:
        project = ProjectConfig.autogenerate(
            root, SerenaConfig(), languages=[LanguageServerId(x) for x in languages],
            save_to_disk=False,
        )._to_yaml_dict()
    runtime_path = root / ".serena/runtime/serena_config.yml"
    runtime = yaml.load((runtime_path if runtime_path.exists() else Path(SERENA_CONFIG_TEMPLATE_FILE)).read_text())
    print(json.dumps({"project": project, "runtime": runtime}))


if __name__ == "__main__":
    main()
