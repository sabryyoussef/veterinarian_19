def migrate(cr, version):
    """Backfill media_kind/has_media for existing rows (no inbox_state here)."""
    cr.execute(
        """
        UPDATE whatsapp_message
           SET media_kind = CASE
                WHEN lower(coalesce(body,'')) LIKE '%%[image]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=image%%'
                  THEN 'image'
                WHEN lower(coalesce(body,'')) LIKE '%%[video]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=video%%'
                  THEN 'video'
                WHEN lower(coalesce(body,'')) LIKE '%%[audio]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=audio%%'
                  THEN 'audio'
                WHEN lower(coalesce(body,'')) LIKE '%%[document]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=document%%'
                  THEN 'document'
                WHEN lower(coalesce(body,'')) LIKE '%%[sticker]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=sticker%%'
                  THEN 'sticker'
                WHEN lower(coalesce(body,'')) LIKE '%%[reaction]%%'
                  OR lower(coalesce(attachment_references,'')) LIKE '%%media_type=reaction%%'
                  THEN 'reaction'
                WHEN coalesce(attachment_references,'') <> ''
                  THEN 'unknown'
                ELSE 'none'
           END,
               has_media = CASE
                WHEN coalesce(attachment_references,'') <> '' THEN true
                WHEN lower(coalesce(body,'')) ~ '\\[(image|video|audio|document|sticker|reaction)\\]'
                  THEN true
                ELSE false
           END
         WHERE media_kind IS NULL OR media_kind = 'none'
            OR has_media IS DISTINCT FROM (
                CASE
                  WHEN coalesce(attachment_references,'') <> '' THEN true
                  WHEN lower(coalesce(body,'')) ~ '\\[(image|video|audio|document|sticker|reaction)\\]'
                    THEN true
                  ELSE false
                END
            )
        """
    )
