# Pinned f85d140 native detail-loop excerpt. Success parsing is replaced by a local callback.
# Source: ai-goofish-monitor/src/scraper.py, f85d140b6b45029d9a0925feb96dad733b41396d.
# MIT License
#
# Copyright (c) 2025 dingyufei615
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

async def scrape_xianyu(task_config: dict, debug_limit: int=0):
    for page_num in range(2):
        pages.append(page_num)
        for number in range(3):
            item_data = {'id': page_num * 3 + number, 'link': 'https://monitor.test/item?id=' + str(100 + number)}
            detail_page = make_page(item_data['id'])
            try:
                async with detail_page.expect_response(lambda r: DETAIL_API_URL_PATTERN in r.url, timeout=25000) as detail_info:
                    await detail_page.goto(item_data['link'], wait_until='domcontentloaded', timeout=25000)
                detail_response = await detail_info.value
                if detail_response.ok:
                    detail_json = await detail_response.json()
                    ret_string = str(await safe_get(detail_json, 'ret', default=[]))
                    if 'FAIL_SYS_USER_VALIDATE' in ret_string:
                        print('\n==================== CRITICAL BLOCK DETECTED ====================')
                        print('检测到闲鱼反爬虫验证 (FAIL_SYS_USER_VALIDATE)，程序将终止。')
                        long_sleep_duration = random.randint(3, 60)
                        print(f'为避免账户风险，将执行一次长时间休眠 ({long_sleep_duration} 秒) 后再退出...')
                        await asyncio.sleep(long_sleep_duration)
                        print('长时间休眠结束，现在将安全退出。')
                        print('===================================================================')
                        raise RiskControlError('FAIL_SYS_USER_VALIDATE')
                    saved.append(item_data['id'])
            except PlaywrightTimeoutError:
                print(f'   错误: 访问商品详情页或等待API响应超时。')
            except Exception as e:
                print(f'   错误: 处理商品详情时发生未知错误: {e}')
            finally:
                await detail_page.close()
                await random_sleep(2, 4)
