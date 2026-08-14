import { PagePlaceholder } from '@/components/PagePlaceholder'

/**
 * 文档解析页：导入 txt / md / docx 文档，解析为候选知识卡并确认导入。
 */
export default function DocumentParse() {
  return (
    <PagePlaceholder
      title="文档解析"
      description="导入资料文档，自动提取设定并导入知识库"
    >
      <p className="text-sm text-slate-400">
        尚未实现。后续将提供拖拽上传（react-dropzone）、解析进度与候选卡片预览。
      </p>
    </PagePlaceholder>
  )
}
