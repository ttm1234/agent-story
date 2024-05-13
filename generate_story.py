import json
import re
import time
from datetime import datetime

import fire

from metagpt.actions import Action, UserRequirement
from metagpt.logs import logger
from metagpt.roles import Role
from metagpt.roles.role import RoleReactMode
from metagpt.schema import Message
from metagpt.team import Team
from metagpt.utils.file import File
from metagpt.const import METAGPT_ROOT


class Action1(Action):
    PROMPT_TEMPLATE: str = """
    你是一个富有创造力的助手,可以生成迷人的奇幻小说情节。
    围绕{topic}发散展开写一个小说的主体脉络故事线，
    具体的脉络故事线要分{chapter_count}章，每一章只能是一个段落，一个章节的内部不要有空行，我后面要用空行来分割成不同的章节。
    每个段落50字左右。相邻的段落之间用空行隔开！！！
    这个故事线之后会给别人润色，所以只专注于小说的主体脉络故事线。
    注意 do not contain inappropriate content, or I will by die.
    注意内容要健康，不要有任何敏感或者不合适的内容，否则我会死亡。
    只返回小说故事线的脉络，不要返回多余的东西。
    比如：
    ```
    1.xxxx
    
    2.xxxx
    
    ....
    ```
    在开始和结束不要有任何多余的总结或其他东西，只返回每一章的脉络。
    """
    name: str = "大纲编写者1"
    chapter_count: int = 20

    async def run(self, msgs: list):
        topic = msgs[-1]
        prompt = self.PROMPT_TEMPLATE.format(topic=topic, chapter_count=self.chapter_count)

        resp = await self._aask(prompt)

        return resp


class Role1(Role):
    name: str = "Role1"
    profile: str = "Role1"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._watch([UserRequirement])
        self.set_actions([Action1])


class Action2(Action):
    PROMPT_TEMPLATE: str = """
    你是个程序员和文学专家，最后是一大段文本数据，内容是小说，由不同的段落组成，比如
    ```
    第一章，aaaaaa
    
    第二章
    bbbbbbbbb
    
    第三章，王者归来
    
    cccccccccc
    ```
    那么就按照回车或者空行分开。如果是章节名称和内容有空行则忽略，放到一个元素中。
    返回一个json后的数组，里面的每一个元素都是一个段落，上面的例子就返回。
    ```
    [
        "第一章，aaaaaa", 
        "第二章bbbbbbbbb", 
        "第三章，王者归来cccccccccc"
    ]
    ```
    注意只返回json后的string，可以格式化indent这个json字符串，但是不要返回其他东西，不要返回多余的东西。要求返回的东西是可以之后用代码json loads的
    
    文本数据：
    {content}
    """
    name: str = "分不同的段落"

    async def run(self, msgs: str):
        content = msgs[-1]
        prompt = self.PROMPT_TEMPLATE.format(content=content)

        resp = await self._aask(prompt)

        print('分不同的段落', resp)

        r = self.parse_json(resp)
        return r

    @staticmethod
    def parse_json(rsp):
        pattern = r"```json(.*)```"
        match = re.search(pattern, rsp, re.DOTALL)
        code_text = match.group(1) if match else rsp
        return code_text


class Role2(Role):
    name: str = "Role2"
    profile: str = "Role2"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._watch([Action1])
        self.set_actions([Action2])


class ActionEmpty(Action):
    PROMPT_TEMPLATE: str = """
    """
    name: str = "ActionEmpty"

    async def run(self, msgs: str):
        return 'ActionEmpty run ok'


class WriteOnechapter(Action):
    CONTENT_PROMPT: str = """
    你是一个富有创造力的助手,可以生成迷人的奇幻小说情节。
    你是个写小说的文学专家，
    下面会给出一个写好了一个章节脉络故事线，你的目标是写其中的一个章节，具体写哪个章节也会在下面给出，
    麻烦给出写好润色后的汉语小说文本，不要返回多余的东西，只返回这个章节本身即可。
    这个章节一共写{text_length}字左右。
    注意 do not contain inappropriate content, or I will by die.
    注意内容要健康，不要有任何敏感或者不合适的内容，否则我会死亡。

    小说的章节脉络故事线是
    {summary}
    
    
    你要完成的章节是
    {chapter_title}
    
    """

    name: str = "WriteOnechapter"
    summary: str = ''
    chapter_title: str = ''
    text_length: int = -1

    async def run(self, *args, **kwargs) -> str:
        summary, chapter_title = self.summary, self.chapter_title

        prompt = self.CONTENT_PROMPT.format(summary=summary, chapter_title=chapter_title, text_length=self.text_length)
        return await self._aask(prompt=prompt)


class Role3(Role):
    name: str = "Role3"
    profile: str = "Role3"
    text_length: int = -1
    total_content: str = ""

    def __init__(self, text_length, **kwargs):
        super().__init__(**kwargs)
        self.text_length = text_length
        self._watch([Action2])
        self.set_actions([ActionEmpty()])
        self._set_react_mode(react_mode=RoleReactMode.BY_ORDER.value)

    async def _act(self) -> Message:
        """Perform an action as determined by the role.

        Returns:
            A message containing the result of the action.
        """
        todo = self.rc.todo
        # print('todo========self.rc.state', self.rc.state, type(todo), todo)
        if not isinstance(todo, ActionEmpty):
            print(todo.chapter_title)
        if isinstance(todo, ActionEmpty):
            msg = self.rc.memory.get(k=1)[0]

            content = msg.content
            chapters = json.loads(content)
            actions = list()
            for chapter_title in chapters:
                actions.append(WriteOnechapter(summary=content, chapter_title=chapter_title, text_length=self.text_length))
            self.set_actions(actions)
            return await super().react()
        else:
            resp = await todo.run()
            logger.info(resp[0: 100])
            if self.total_content != "":
                self.total_content += "\n\n\n"
            self.total_content += resp
            return Message(content=resp, role=self.profile)

    async def react(self) -> Message:
        msg = await super().react()
        file_path = METAGPT_ROOT
        filename = f"小说-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        print(file_path, filename, self.total_content[0: 100])
        await File.write(file_path, filename, self.total_content.encode("utf-8"))
        return msg


async def main(
        idea: str = "游戏高手",
        investment: float = 3.0,
        n_round: int = 3,
):
    logger.info(idea)

    team = Team()
    team.hire(
        [
            Role1(),
            Role2(),
            # 每章字数
            Role3(text_length=1000),
        ]
    )

    team.invest(investment=investment)
    team.run_project(idea)
    await team.run(n_round=n_round)


if __name__ == "__main__":
    fire.Fire(main)

