/**
 * UI 基座统一出口 —— 页面只从这里引入，避免各页散落 import 路径
 *
 * 改版前项目只有 5 个组件、没有任何基础 UI 组件，每页都在手写
 * 按钮/卡片/徽标/输入框的类名（硬编码颜色 200+ 处）。这一层就是为了终结那种状态。
 */
export { default as Button } from "./Button";
export { default as Card } from "./Card";
export { default as Badge } from "./Badge";
export { default as Tabs } from "./Tabs";
export { default as SectionHeader } from "./SectionHeader";
export { Input, Textarea, Select, Field } from "./Form";
export {
  Skeleton,
  ImageSkeleton,
  LineSkeleton,
  CardSkeleton,
  SkeletonGrid,
  EmptyState,
} from "./Skeleton";

export type { ButtonProps } from "./Button";
export type { CardProps } from "./Card";
export type { TabItem } from "./Tabs";