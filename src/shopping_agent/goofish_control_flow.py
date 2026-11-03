"""Narrow in-memory repair for the pinned upstream detail-loop contract.

No reference files are edited. Unknown shapes fail before browser startup.
"""
import ast
import copy
import inspect
import textwrap


class CompatibilityError(RuntimeError):
    pass


def _call(node, owner, method):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == owner
            and node.func.attr == method)


def repair_detail_control_flow(scraper, *, on_control_failure=None):
    """Propagate verification/login failures; keep ordinary item errors local."""
    try:
        original = scraper.scrape_xianyu
        tree = ast.parse(textwrap.dedent(inspect.getsource(original)))
        function = tree.body[0]
        if (len(tree.body) != 1 or not isinstance(function, ast.AsyncFunctionDef)
                or function.name != "scrape_xianyu" or function.decorator_list):
            raise CompatibilityError()
        details = [n for n in ast.walk(function) if isinstance(n, ast.Try)
                   and any(_call(c, "detail_page", "close") for f in n.finalbody for c in ast.walk(f))
                   and any(_call(c, "detail_page", "expect_response") for b in n.body for c in ast.walk(b))]
        # The outer try also includes detail.close in its body, but not in its
        # finally: this identifies the actual per-item handler, not all catches.
        if len(details) != 1:
            raise CompatibilityError()
        detail = details[0]
        if [ast.unparse(h.type) if h.type else None for h in detail.handlers] != ["PlaywrightTimeoutError", "Exception"]:
            raise CompatibilityError()
        validation = [n for n in ast.walk(detail) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == "'FAIL_SYS_USER_VALIDATE' in ret_string"]
        navigations = [n for n in ast.walk(detail) if isinstance(n, ast.Expr)
                       and isinstance(n.value, ast.Await) and _call(n.value.value, "detail_page", "goto")]
        if len(validation) != 1 or len(navigations) != 1:
            raise CompatibilityError()
        for name in ("RiskControlError", "LoginRequiredError"):
            if not issubclass(getattr(scraper, name), Exception):
                raise CompatibilityError()
        if not callable(scraper._is_login_url):
            raise CompatibilityError()

        # Detection already happened: do not sleep up to 60 seconds before
        # reporting it, or let the generic handler continue to the next item.
        validation[0].body = ast.parse('_shopping_monitor_control_failure("verification_required")\nraise RiskControlError("FAIL_SYS_USER_VALIDATE")').body
        detail.handlers.insert(0, ast.parse("try:\n pass\nexcept (RiskControlError, LoginRequiredError):\n raise").body[0].handlers[0])
        checks = ast.parse('''
if _is_login_url(detail_page.url):
    _shopping_monitor_control_failure("login_required")
    raise LoginRequiredError("monitor_login_required")
if await detail_page.locator("div.baxia-dialog-mask").is_visible() or await detail_page.locator("div.J_MIDDLEWARE_FRAME_WIDGET").is_visible():
    _shopping_monitor_control_failure("verification_required")
    raise RiskControlError("monitor_verification_required")
''').body
        navigation = navigations[0]

        class NavigationCheck(ast.NodeTransformer):
            def visit_Expr(self, node):
                if node is navigation:
                    return [node, *copy.deepcopy(checks)]
                return self.generic_visit(node)

        NavigationCheck().visit(function)
        # A navigation/response timeout can itself be a login redirect or
        # verification layer. Check before keeping the native timeout behavior.
        detail.handlers[1].body[0:0] = copy.deepcopy(checks)
        ast.fix_missing_locations(tree)
        code = compile(tree, original.__code__.co_filename, "exec")
    except (AttributeError, OSError, TypeError, ValueError, SyntaxError, IndexError):
        raise CompatibilityError("Unsupported monitor detail contract") from None
    except CompatibilityError:
        raise CompatibilityError("Unsupported monitor detail contract") from None
    def publish(code):
        try:
            if on_control_failure:
                on_control_failure(code)
        except Exception:
            pass  # Reporting cannot swallow the control exception that follows.
    scraper._shopping_monitor_control_failure = publish
    exec(code, scraper.__dict__)
