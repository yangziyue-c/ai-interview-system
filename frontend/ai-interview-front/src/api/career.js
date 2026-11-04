import request from '@/utils/request'

// 岗位倾向速测：题目与计分都在后端，前端只负责答题与展示
export const getCareerQuestions = () => request.get('/career-anchor/questions')

// answers 为 20 条 1~5 评分，顺序与题目接口返回一致
export const submitCareerAnswers = (answers) =>
    request.post('/career-anchor/submit', { answers })
