-- CPD-151: у публикуемого ключа (роль anon) и у роли authenticated отзываются избыточные права
-- на боевые таблицы. Применено 05.09.2026 тремя группами, каждая с проверкой снаружи до и после.
--
-- Что было: обе роли имели ПОЛНЫЙ набор (INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES,
-- TRIGGER, MAINTAIN) на пять таблиц, и доступ держался одним рубежом — построчной защитой без
-- политик. Снаружи это выглядело как `200 []`, а не как отказ: одна разрешающая политика открыла бы
-- 46 отпечатков машин и весь журнал на чтение и на удаление.
--
-- Корень — не чья-то выдача, а права ПО УМОЛЧАНИЮ схемы public: каждая новая таблица рождалась с
-- полным набором. Поэтому вместе с таблицами правится и умолчание (группа 3); device_bindings от
-- 30.08 потому и чиста, что её миграция отзывала права вручную.
--
-- Что сознательно СОХРАНЕНО: чтение app_versions и content_versions. Там есть осознанные политики
-- (проверка обновлений установленных программ), и путь доказан живым: публикуемый ключ отдаёт
-- оттуда данные. Право и политика — независимые рубежи; снять право значило бы закрыть путь раньше,
-- чем сработает разрешающая политика. Отказ невиновному дороже пропуска виноватого.
--
-- Что сознательно НЕ ТРОНУТО:
--   * storage.* — та же картина прав, но хранилище управляется платформой; отдельная работа.
--   * умолчания владельца supabase_admin — роль postgres их править не может; наши миграции идут
--     от postgres, так что для нас корень закрыт, остаток относится к таблицам самой платформы.

-- Группа 1. Таблицы, куда публикуемому ключу ходить незачем: снять всё.
revoke all on public.activations from anon, authenticated;
revoke all on public.audit_log   from anon, authenticated;

-- licenses — применено отдельным шагом по слову владельца в тот же день. Контракт 05.07
-- (anon-чтение под узкой политикой product='thin-client') пересмотрен им же 23.08 при закрытии
-- П2-1: «открыть таблицу для anon нельзя; снимок готовится на доверенной машине, ключей к базе на
-- узле нет вовсе». Проверено на узле Б лично: ключа нет, таймера нет, снимок от 22.08 готовился
-- служебным ключом с машины владельца. Инструмент sync_licenses.py не задет.
revoke all on public.licenses    from anon, authenticated;

-- Группа 2. Таблицы с живым чтением: снять всё и вернуть ровно чтение — ОДНИМ пакетом, чтобы не
-- было окна, в котором право уже снято, а обратно ещё не выдано.
revoke all on public.app_versions     from anon, authenticated;
revoke all on public.content_versions from anon, authenticated;
grant select on public.app_versions     to anon, authenticated;
grant select on public.content_versions to anon;

-- Группа 3. Корень: новые таблицы схемы public больше не рождаются открытыми.
alter default privileges in schema public revoke all on tables from anon, authenticated;

-- PostgREST кеширует права: без этого проверка снаружи сразу после применения покажет СТАРОЕ
-- поведение и даст ложную зелень.
notify pgrst, 'reload schema';

-- Откат целиком:
--   grant all on public.activations, public.audit_log, public.app_versions, public.content_versions
--         to anon, authenticated;
--   alter default privileges in schema public grant all on tables to anon, authenticated;
--   notify pgrst, 'reload schema';
-- Мера не трогает ни строки, ни схему — только права; данным откат не нужен.
