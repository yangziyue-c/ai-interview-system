// 全局 mock 开关：默认走真实接口，只有显式 VITE_USE_MOCK=true 时才启用假数据。
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
