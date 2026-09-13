<script>
  /**
   * Мок ConfigPanel для теста поведенческого сторожа кнопки обращения (s46).
   * Настоящий ConfigPanel — тяжёлая форма настроек обучения, к делу не относится:
   * тест проверяет цепочку ModelTrainingStep → TrainingProgress → ошибка → кнопка
   * обращения, а не саму форму. Кнопка ниже воспроизводит ровно то, что делает
   * настоящая панель при старте асинхронного обучения — зовёт onTrainingStarted(taskId).
   */
  let { onTrainingStarted } = $props();
</script>

<button type="button" data-testid="mock-config-start" onclick={() => onTrainingStarted?.('task-mock-1')}>
  Обучить (мок)
</button>
