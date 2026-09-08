-- CPD-151 — отзыв прав публикуемого ключа на боевых таблицах
-- Подготовлено 2026-09-07. Согласовано владельцем 01.09 и подтверждено 07.09.
-- Порядок обязателен: ШАГ 1 (снимок) → ШАГ 2 (обратная команда по снимку) → ШАГ 3 (отзыв) → ШАГ 4 (проверка).
-- ШАГ 3 НЕ выполнять, пока вывод ШАГА 1 не сохранён.

-- ============ ШАГ 1. СНИМОК ТЕКУЩИХ ПРАВ (только чтение) ============
-- 1.1 Кому и что выдано по трём таблицам
select table_name, grantee, privilege_type, is_grantable
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('licenses','activations','audit_log','content_versions','app_versions','device_bindings')
  and grantee in ('anon','authenticated','PUBLIC')
order by table_name, grantee, privilege_type;

-- 1.2 Включена ли построчная защита и принудительна ли она
select c.relname as table_name,
       c.relrowsecurity  as rls_enabled,
       c.relforcerowsecurity as rls_forced
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'r'
  and c.relname in ('licenses','activations','audit_log','content_versions','app_versions','device_bindings')
order by 1;

-- 1.3 Какие политики есть (пусто у licenses/activations/audit_log = единственный рубеж отсутствует)
select schemaname, tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('licenses','activations','audit_log','content_versions','app_versions','device_bindings')
order by tablename, policyname;

-- 1.4 Права на последовательности этих таблиц (чтобы отзыв не оставил полу-состояния)
select sequence_schema, sequence_name, grantee, privilege_type
from information_schema.role_usage_grants
where object_schema = 'public' and grantee in ('anon','authenticated','PUBLIC');

-- ============ ШАГ 2. ОБРАТНАЯ КОМАНДА (сгенерировать ДО отзыва) ============
-- Выполнить и СОХРАНИТЬ вывод — это готовый откат, дословно.
select string_agg(
         format('grant %s on public.%I to %I;', privilege_type, table_name, grantee),
         E'\n' order by table_name, grantee, privilege_type)
       as rollback_script
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('licenses','activations','audit_log')
  and grantee in ('anon','authenticated');

-- ============ ШАГ 3. ОТЗЫВ (необратимо для клиентов немедленно) ============
-- Выполнять ТОЛЬКО после сохранения вывода шагов 1 и 2.
-- revoke all снимает и select — это осознанно: клиенты в эти таблицы напрямую не ходят,
-- обращения идут в серверные функции под служебным ключом (доказано разведкой 07.09).
revoke all on public.licenses    from anon, authenticated;
revoke all on public.activations from anon, authenticated;
revoke all on public.audit_log   from anon, authenticated;

-- content_versions и app_versions НЕ трогаем: у них есть осмысленные разрешающие политики,
-- судьбу решать отдельно (решение владельца 01.09).

-- ============ ШАГ 4. ПРОВЕРКА ПОСЛЕ ОТЗЫВА ============
-- 4.1 По трём таблицам не должно остаться ни одной строки
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('licenses','activations','audit_log')
  and grantee in ('anon','authenticated','PUBLIC')
order by 1,2,3;

-- 4.2 Живая проверка «глазами клиента» — выполняется НЕ здесь, а из программы:
--     запустить установленную Эконометрику, пройти активацию лицензии и обмен сигналами.
--     Ожидание: работает как раньше (ходит в функции под служебным ключом).
