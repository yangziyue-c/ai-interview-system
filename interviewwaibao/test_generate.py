import requests
import json

url = "http://127.0.0.1:8000/generate"

# 完整历史（1~8轮）
history = [
    # 第1轮：开场题
    {"role": "interviewer", "content": "CSS盒模型包含哪些部分？标准盒模型与IE盒模型有何区别？"},
    {"role": "candidate", "content": "盒模型由content、padding、border、margin组成。标准盒模型width只包含content，IE盒模型width包含content+padding+border。"},
    # 第2轮：L1 追问
    {"role": "interviewer", "content": "box-sizing在实际布局中的应用场景"},
    {"role": "candidate", "content": "在实际开发中，我们会用box-sizing:border-box来让元素的总宽度固定，方便响应式布局。"},
    # 第3轮：深度考察1（React Fiber）
    {"role": "interviewer", "content": "React Fiber架构如何解决栈溢出问题？其时间切片机制如何工作？"},
    {"role": "candidate", "content": "Fiber把渲染拆分成可中断的小单元，通过时间切片让高优先级任务先执行。"},
    # 第4轮：降级追问（React Fiber基础）
    {"role": "interviewer", "content": "这个问题比较深入。先聊聊——你知道这个技术主要用来解决什么问题吗？"},
    {"role": "candidate", "content": "主要用于解决React 15中递归diff卡顿的问题。"},
    # 第5轮：深度考察2（项目题-首屏优化）
    {"role": "interviewer", "content": "在你的项目中，首屏加载做了哪些优化？如何验证效果？"},
    {"role": "candidate", "content": "做了代码分割、图片懒加载、关键CSS内联，用Lighthouse验证FCP从2.5s降到1.2s。"},
    # 第6轮：深度考察3（算法题-全排列）
    {"role": "interviewer", "content": "请实现一个函数，生成给定数组的所有全排列（含去重）"},
    {"role": "candidate", "content": "我使用回溯法加排序去重，先排序，然后递归交换，用set记录当前位置用过的字符来去重。"},
    # 第7轮：收尾交流（行为面试题）
    {"role": "interviewer", "content": "请描述一次你经历职业低谷或倦怠期，如何调整恢复的\n\n【岗位软技能考察：用户体验思维】"},
    {"role": "candidate", "content": "我在2023年初经历过一段职业倦怠期，当时项目节奏快、重复工作多，感觉成长停滞。我的调整方式是：1）主动和mentor沟通，调整了工作重心；2）利用业余时间学习新技能（当时学了React Native）；3）坚持每周运动。大概3个月后恢复了状态，而且技术视野也拓宽了。"}
]

# 第9轮请求
payload = {
    "need_audio": True,
    "position": "frontend",
    "round": 9,
    "is_follow_up": True,
    "history": history
}

print("🚀 测试第9轮（预期最终收尾题）\n")
resp = requests.post(url, json=payload)
print(f"状态码: {resp.status_code}")
if resp.status_code == 200:
    print(f"返回: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
else:
    print(f"错误: {resp.text}")