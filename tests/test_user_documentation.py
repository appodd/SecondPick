"""Documentation contracts for the shipped application and privacy boundary."""
from pathlib import Path
import re


def test_maintained_documentation_links_exist():
    documents = [Path('README.md'), *Path('docs').glob('*.md')]
    # Only tracked release documents; historical notes are local-only.
    maintained = {'README.md', 'README.en.md', 'user-guide.md', 'PRIVACY.md', 'DEVELOPMENT.md',
                  'VALIDATION.md', 'architecture.md', 'account-risk.md', 'platform-spike.md'}
    documents.append(Path('README.en.md'))
    for path in documents:
        if path.name not in maintained:
            continue
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' not in target and not target.startswith('#'):
                assert (path.parent / target.split('#')[0]).exists(), (path, target)


def test_first_use_does_not_promise_seeded_data_or_automatic_scope_changes():
    guide = Path('docs/user-guide.md').read_text(encoding='utf-8')
    assert '全新数据目录没有选购项目或商品' in guide
    assert '监控搜索范围不会自动修改' in guide
    assert '保持浏览器打开' in guide
    assert '1800' in guide
    assert '不绕过验证' in guide


def test_documentation_discloses_model_transfer_and_measured_validation_limits():
    readme = Path('README.md').read_text(encoding='utf-8')
    assert '发送' in readme and '模型服务' in readme
    english = Path('README.en.md').read_text(encoding='utf-8')
    validation = Path('docs/VALIDATION.md').read_text(encoding='utf-8')
    assert '完整后端回归和长期运行验收尚未完成' not in readme
    assert '2026-11-03' in validation and '1404' in validation and '1374' in validation
    assert '真实平台采集' in validation and '长期运行' in validation
    assert 'docs/VALIDATION.md' in readme and 'docs/VALIDATION.md' in english
    for platform in ('JD', 'Taobao', 'Zhuanzhuan'):
        assert platform in readme and platform in english
    assert '未提供完整的自动卖家主页' in readme
    assert 'automatic seller-homepage' in english
