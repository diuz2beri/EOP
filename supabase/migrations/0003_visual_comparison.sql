begin;

-- Visual comparison is the safe default: public imagery becomes a private draft
-- and still requires a logged human approval before it enters the timeline.
update aois
set product_recipes = array_prepend('visual-comparison', product_recipes)
where not ('visual-comparison' = any(product_recipes));

commit;
